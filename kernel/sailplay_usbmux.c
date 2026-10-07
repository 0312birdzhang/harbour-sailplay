// SPDX-License-Identifier: GPL-2.0
/*
 * sailplay_usbmux: minimal USBMUX composite function for CarPlay probing.
 *
 * Presents the Apple USBMUX device interface (EF/02/01) with bulk OUT 0x04
 * and bulk IN 0x85, and exposes both directions through /dev/sailplay%d.
 */

#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/idr.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/types.h>
#include <linux/usb/composite.h>
#include <linux/usb/gadget.h>
#include <linux/wait.h>

#define SAILPLAY_MINORS		4
#define SAILPLAY_BUF_SIZE	16384
#define SAILPLAY_CLASS		"sailplay"
#define SAILPLAY_DEV_FMT	"sailplay%d"

#define USBMUX_CLASS	0xEF
#define USBMUX_SUBCLASS	0x02
#define USBMUX_PROTOCOL	0x01

#define USBMUX_OUT_EP	0x04
#define USBMUX_IN_EP	0x85

struct sailplay_mux {
	struct usb_function_instance inst;
	struct usb_function func;

	int minor;

	struct cdev cdev;
	dev_t dev;
	struct device *dev_node;

	struct usb_ep *in_ep;
	struct usb_ep *out_ep;

	struct usb_request *in_req;
	struct usb_request *out_req;

	u8 *in_buf;
	u8 *out_buf;

	spinlock_t in_lock;
	spinlock_t out_lock;
	wait_queue_head_t in_wait;
	wait_queue_head_t out_wait;

	struct usb_interface_descriptor interface_desc;
	struct usb_endpoint_descriptor fs_desc[2];
	struct usb_endpoint_descriptor hs_desc[2];
	struct usb_endpoint_descriptor ss_desc[2];
	struct usb_descriptor_header *fs_descriptors[4];
	struct usb_descriptor_header *hs_descriptors[4];
	struct usb_descriptor_header *ss_descriptors[4];

	struct usb_string string_defs[2];
	struct usb_gadget_strings string_tab;
	struct usb_gadget_strings *string_tabs[2];
};

static struct class *sailplay_class;
static DEFINE_IDR(sailplay_idr);
static DEFINE_MUTEX(sailplay_idr_lock);
static dev_t sailplay_dev;

static struct sailplay_mux *to_mux(struct usb_function *f)
{
	return container_of(f, struct sailplay_mux, func);
}

static struct sailplay_mux *to_mux_inst(struct usb_function_instance *inst)
{
	return container_of(inst, struct sailplay_mux, inst);
}

static void sailplay_complete(struct usb_ep *ep, struct usb_request *req)
{
	struct sailplay_mux *mux = req->context;

	if (ep == mux->in_ep) {
		spin_lock(&mux->in_lock);
		mux->in_req = NULL;
		spin_unlock(&mux->in_lock);
		wake_up_all(&mux->in_wait);
	} else {
		spin_lock(&mux->out_lock);
		mux->out_req = NULL;
		spin_unlock(&mux->out_lock);
		wake_up_all(&mux->out_wait);
	}
}

static int sailplay_queue_in(struct sailplay_mux *mux, u32 len)
{
	struct usb_request *req;
	int rc;

	if (!mux->in_ep)
		return -ENODEV;

	req = usb_ep_alloc_request(mux->in_ep, GFP_ATOMIC);
	if (!req)
		return -ENOMEM;

	req->buf = mux->in_buf;
	req->length = min_t(u32, len, SAILPLAY_BUF_SIZE);
	req->context = mux;
	req->complete = sailplay_complete;

	rc = usb_ep_queue(mux->in_ep, req, GFP_ATOMIC);
	if (rc) {
		usb_ep_free_request(mux->in_ep, req);
		return rc;
	}

	spin_lock(&mux->in_lock);
	mux->in_req = req;
	spin_unlock(&mux->in_lock);
	return 0;
}

static int sailplay_queue_out(struct sailplay_mux *mux)
{
	struct usb_request *req;
	int rc;

	if (!mux->out_ep)
		return -ENODEV;

	req = usb_ep_alloc_request(mux->out_ep, GFP_ATOMIC);
	if (!req)
		return -ENOMEM;

	req->buf = mux->out_buf;
	req->length = SAILPLAY_BUF_SIZE;
	req->context = mux;
	req->complete = sailplay_complete;

	rc = usb_ep_queue(mux->out_ep, req, GFP_ATOMIC);
	if (rc) {
		usb_ep_free_request(mux->out_ep, req);
		return rc;
	}

	spin_lock(&mux->out_lock);
	mux->out_req = req;
	spin_unlock(&mux->out_lock);
	return 0;
}

static void sailplay_disable_eps(struct sailplay_mux *mux)
{
	if (mux->in_ep) {
		spin_lock(&mux->in_lock);
		mux->in_req = NULL;
		spin_unlock(&mux->in_lock);
		usb_ep_disable(mux->in_ep);
		mux->in_ep = NULL;
	}

	if (mux->out_ep) {
		spin_lock(&mux->out_lock);
		mux->out_req = NULL;
		spin_unlock(&mux->out_lock);
		usb_ep_disable(mux->out_ep);
		mux->out_ep = NULL;
	}

	wake_up_all(&mux->in_wait);
	wake_up_all(&mux->out_wait);
}

static int sailplay_set_alt(struct usb_function *f, unsigned intf, unsigned alt)
{
	struct sailplay_mux *mux = to_mux(f);
	struct usb_composite_dev *cdev = f->config->cdev;
	int rc;

	if (alt != 0)
		return -EPROTO;

	sailplay_disable_eps(mux);

	rc = config_ep_by_speed(cdev->gadget, f, mux->in_ep);
	if (rc)
		return rc;
	rc = usb_ep_enable(mux->in_ep);
	if (rc) {
		mux->in_ep = NULL;
		return rc;
	}
	mux->in_ep->driver_data = mux;

	rc = config_ep_by_speed(cdev->gadget, f, mux->out_ep);
	if (rc) {
		usb_ep_disable(mux->in_ep);
		mux->in_ep = NULL;
		return rc;
	}
	rc = usb_ep_enable(mux->out_ep);
	if (rc) {
		usb_ep_disable(mux->in_ep);
		mux->in_ep = NULL;
		mux->out_ep = NULL;
		return rc;
	}
	mux->out_ep->driver_data = mux;

	rc = sailplay_queue_out(mux);
	if (rc)
		goto fail_out;

	rc = sailplay_queue_in(mux, SAILPLAY_BUF_SIZE);
	if (rc)
		goto fail_out;

	return 0;

fail_out:
	usb_ep_disable(mux->out_ep);
	mux->out_ep = NULL;
	usb_ep_disable(mux->in_ep);
	mux->in_ep = NULL;
	return rc;
}

static void sailplay_disable(struct usb_function *f)
{
	sailplay_disable_eps(to_mux(f));
}

static void sailplay_suspend(struct usb_function *f)
{
}

static void sailplay_resume(struct usb_function *f)
{
}

static int sailplay_bind(struct usb_configuration *c, struct usb_function *f)
{
	struct sailplay_mux *mux = to_mux(f);
	struct usb_ep *ep;
	int status;

	status = usb_interface_id(c, f);
	if (status < 0)
		return status;
	mux->interface_desc.bInterfaceNumber = status;

	ep = usb_ep_autoconfig(c->cdev->gadget, &mux->fs_desc[0]);
	if (!ep)
		return -ENODEV;
	mux->out_ep = ep;

	ep = usb_ep_autoconfig(c->cdev->gadget, &mux->fs_desc[1]);
	if (!ep)
		return -ENODEV;
	mux->in_ep = ep;

	status = usb_assign_descriptors(f,
		mux->fs_descriptors,
		mux->hs_descriptors,
		mux->ss_descriptors,
		NULL);
	if (status)
		return status;

	return 0;
}

static void sailplay_unbind(struct usb_configuration *c, struct usb_function *f)
{
	sailplay_disable_eps(to_mux(f));
	usb_free_all_descriptors(f);
}

static void sailplay_free_func(struct usb_function *f)
{
	struct sailplay_mux *mux = to_mux(f);

	device_destroy(sailplay_class, mux->dev);
	cdev_del(&mux->cdev);
	idr_remove(&sailplay_idr, mux->minor);
	kfree(mux->in_buf);
	kfree(mux->out_buf);
}

static void sailplay_free_inst_cfg(struct config_item *item)
{
	kfree(container_of(to_config_group(item), struct sailplay_mux, inst.group));
}

static void sailplay_free_inst(struct usb_function_instance *inst)
{
	kfree(to_mux_inst(inst));
}

static int sailplay_open(struct inode *inode, struct file *file)
{
	struct sailplay_mux *mux = container_of(inode->i_cdev, struct sailplay_mux, cdev);

	file->private_data = mux;
	return 0;
}

static int sailplay_release(struct inode *inode, struct file *file)
{
	file->private_data = NULL;
	return 0;
}

static ssize_t sailplay_read(struct file *file, char __user *ubuf, size_t count, loff_t *off)
{
	struct sailplay_mux *mux = file->private_data;
	struct usb_request *req;
	unsigned long flags;
	unsigned int len;
	ssize_t rc;

	if (count > SAILPLAY_BUF_SIZE)
		count = SAILPLAY_BUF_SIZE;

	spin_lock_irqsave(&mux->in_lock, flags);
	if (!mux->in_req) {
		spin_unlock_irqrestore(&mux->in_lock, flags);
		if (file->f_flags & O_NONBLOCK)
			return -EAGAIN;
		if (wait_event_interruptible(mux->in_wait, mux->in_req || !mux->in_ep))
			return -ERESTARTSYS;
		spin_lock_irqsave(&mux->in_lock, flags);
		if (!mux->in_req) {
			spin_unlock_irqrestore(&mux->in_lock, flags);
			if (file->f_flags & O_NONBLOCK)
				return -EAGAIN;
			return 0;
		}
	}

	req = mux->in_req;
	len = min_t(unsigned int, count, req->actual);
	spin_unlock_irqrestore(&mux->in_lock, flags);

	rc = copy_to_user(ubuf, mux->in_buf, len) ? -EFAULT : len;
	if (rc < 0)
		return rc;

	if (sailplay_queue_in(mux, SAILPLAY_BUF_SIZE) < 0)
		return 0;
	return rc;
}

static ssize_t sailplay_write(struct file *file, const char __user *ubuf, size_t count, loff_t *off)
{
	struct sailplay_mux *mux = file->private_data;
	struct usb_request *req;
	unsigned long flags;
	unsigned int len;
	ssize_t rc;

	if (count > SAILPLAY_BUF_SIZE)
		count = SAILPLAY_BUF_SIZE;
	if (!count)
		return 0;

	spin_lock_irqsave(&mux->out_lock, flags);
	if (mux->out_req) {
		spin_unlock_irqrestore(&mux->out_lock, flags);
		if (file->f_flags & O_NONBLOCK)
			return -EAGAIN;
		if (wait_event_interruptible(mux->out_wait, !mux->out_req || !mux->out_ep))
			return -ERESTARTSYS;
		spin_lock_irqsave(&mux->out_lock, flags);
		if (mux->out_req) {
			spin_unlock_irqrestore(&mux->out_lock, flags);
			if (file->f_flags & O_NONBLOCK)
				return -EAGAIN;
			return 0;
		}
	}

	len = count;
	if (copy_from_user(mux->out_buf, ubuf, len)) {
		spin_unlock_irqrestore(&mux->out_lock, flags);
		return -EFAULT;
	}

	req = usb_ep_alloc_request(mux->out_ep, GFP_KERNEL);
	if (!req) {
		spin_unlock_irqrestore(&mux->out_lock, flags);
		return -ENOMEM;
	}

	req->buf = mux->out_buf;
	req->length = len;
	req->context = mux;
	req->complete = sailplay_complete;

	rc = usb_ep_queue(mux->out_ep, req, GFP_KERNEL);
	if (rc) {
		usb_ep_free_request(mux->out_ep, req);
		spin_unlock_irqrestore(&mux->out_lock, flags);
		return rc;
	}

	mux->out_req = req;
	spin_unlock_irqrestore(&mux->out_lock, flags);
	return len;
}

static unsigned int sailplay_poll(struct file *file, poll_table *wait)
{
	struct sailplay_mux *mux = file->private_data;
	unsigned int mask = 0;
	unsigned long flags;

	poll_wait(file, &mux->in_wait, wait);
	poll_wait(file, &mux->out_wait, wait);

	spin_lock_irqsave(&mux->in_lock, flags);
	if (mux->in_req)
		mask |= POLLIN | POLLRDNORM;
	spin_unlock_irqrestore(&mux->in_lock, flags);

	spin_lock_irqsave(&mux->out_lock, flags);
	if (!mux->out_req)
		mask |= POLLOUT | POLLWRNORM;
	spin_unlock_irqrestore(&mux->out_lock, flags);

	return mask;
}

static const struct file_operations sailplay_fops = {
	.owner = THIS_MODULE,
	.open = sailplay_open,
	.release = sailplay_release,
	.read = sailplay_read,
	.write = sailplay_write,
	.poll = sailplay_poll,
	.llseek = noop_llseek,
};

static struct configfs_item_operations sailplay_item_ops = {
	.release = sailplay_free_inst_cfg,
};

static struct config_item_type sailplay_type = {
	.ct_item_ops = &sailplay_item_ops,
	.ct_owner = THIS_MODULE,
};

static struct usb_function_driver sailplay_usb_func = {
	.name = "sailplay",
	.mod = THIS_MODULE,
};

static void sailplay_fill_descriptors(struct sailplay_mux *mux)
{
	mux->interface_desc.bLength = USB_DT_INTERFACE_SIZE;
	mux->interface_desc.bDescriptorType = USB_DT_INTERFACE;
	mux->interface_desc.bNumEndpoints = 2;
	mux->interface_desc.bInterfaceClass = USBMUX_CLASS;
	mux->interface_desc.bInterfaceSubClass = USBMUX_SUBCLASS;
	mux->interface_desc.bInterfaceProtocol = USBMUX_PROTOCOL;

	mux->fs_desc[0].bLength = USB_DT_ENDPOINT_SIZE;
	mux->fs_desc[0].bDescriptorType = USB_DT_ENDPOINT;
	mux->fs_desc[0].bEndpointAddress = USBMUX_OUT_EP;
	mux->fs_desc[0].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->fs_desc[0].wMaxPacketSize = cpu_to_le16(64);

	mux->fs_desc[1].bLength = USB_DT_ENDPOINT_SIZE;
	mux->fs_desc[1].bDescriptorType = USB_DT_ENDPOINT;
	mux->fs_desc[1].bEndpointAddress = USBMUX_IN_EP;
	mux->fs_desc[1].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->fs_desc[1].wMaxPacketSize = cpu_to_le16(64);

	mux->hs_desc[0].bLength = USB_DT_ENDPOINT_SIZE;
	mux->hs_desc[0].bDescriptorType = USB_DT_ENDPOINT;
	mux->hs_desc[0].bEndpointAddress = USBMUX_OUT_EP;
	mux->hs_desc[0].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->hs_desc[0].wMaxPacketSize = cpu_to_le16(512);

	mux->hs_desc[1].bLength = USB_DT_ENDPOINT_SIZE;
	mux->hs_desc[1].bDescriptorType = USB_DT_ENDPOINT;
	mux->hs_desc[1].bEndpointAddress = USBMUX_IN_EP;
	mux->hs_desc[1].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->hs_desc[1].wMaxPacketSize = cpu_to_le16(512);

	mux->ss_desc[0].bLength = USB_DT_ENDPOINT_SIZE;
	mux->ss_desc[0].bDescriptorType = USB_DT_ENDPOINT;
	mux->ss_desc[0].bEndpointAddress = USBMUX_OUT_EP;
	mux->ss_desc[0].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->ss_desc[0].wMaxPacketSize = cpu_to_le16(1024);

	mux->ss_desc[1].bLength = USB_DT_ENDPOINT_SIZE;
	mux->ss_desc[1].bDescriptorType = USB_DT_ENDPOINT;
	mux->ss_desc[1].bEndpointAddress = USBMUX_IN_EP;
	mux->ss_desc[1].bmAttributes = USB_ENDPOINT_XFER_BULK;
	mux->ss_desc[1].wMaxPacketSize = cpu_to_le16(1024);

	mux->fs_descriptors[0] = (struct usb_descriptor_header *)&mux->interface_desc;
	mux->fs_descriptors[1] = (struct usb_descriptor_header *)&mux->fs_desc[0];
	mux->fs_descriptors[2] = (struct usb_descriptor_header *)&mux->fs_desc[1];
	mux->fs_descriptors[3] = NULL;

	mux->hs_descriptors[0] = (struct usb_descriptor_header *)&mux->interface_desc;
	mux->hs_descriptors[1] = (struct usb_descriptor_header *)&mux->hs_desc[0];
	mux->hs_descriptors[2] = (struct usb_descriptor_header *)&mux->hs_desc[1];
	mux->hs_descriptors[3] = NULL;

	mux->ss_descriptors[0] = (struct usb_descriptor_header *)&mux->interface_desc;
	mux->ss_descriptors[1] = (struct usb_descriptor_header *)&mux->ss_desc[0];
	mux->ss_descriptors[2] = (struct usb_descriptor_header *)&mux->ss_desc[1];
	mux->ss_descriptors[3] = NULL;
}

static struct usb_function_instance *sailplay_alloc_inst(void)
{
	struct sailplay_mux *mux;
	int minor;
	dev_t dev;
	int rc;

	mux = kzalloc(sizeof(*mux), GFP_KERNEL);
	if (!mux)
		return ERR_PTR(-ENOMEM);

	sailplay_fill_descriptors(mux);

	mux->string_defs[0].id = 0;
	mux->string_defs[0].s = "USBMUX";
	mux->string_defs[1].id = 0;
	mux->string_defs[1].s = NULL;
	mux->string_tab.language = 0x0409;
	mux->string_tab.strings = mux->string_defs;
	mux->string_tabs[0] = &mux->string_tab;
	mux->string_tabs[1] = NULL;

	minor = idr_alloc(&sailplay_idr, mux, 0, SAILPLAY_MINORS - 1, GFP_KERNEL);
	if (minor < 0)
		goto err_free_mux;
	mux->minor = minor;

	cdev_init(&mux->cdev, &sailplay_fops);
	dev = MKDEV(MAJOR(sailplay_dev), minor);
	rc = cdev_add(&mux->cdev, dev, 1);
	if (rc)
		goto err_idr;
	mux->dev = dev;

	mux->in_buf = kmalloc(SAILPLAY_BUF_SIZE, GFP_KERNEL);
	if (!mux->in_buf)
		goto err_cdev;
	mux->out_buf = kmalloc(SAILPLAY_BUF_SIZE, GFP_KERNEL);
	if (!mux->out_buf)
		goto err_in_buf;

	mux->dev_node = device_create(sailplay_class, NULL, dev, mux, SAILPLAY_DEV_FMT, minor);
	if (IS_ERR(mux->dev_node)) {
		rc = PTR_ERR(mux->dev_node);
		mux->dev_node = NULL;
		goto err_out_buf;
	}

	config_group_init_type_name(&mux->inst.group, "", &sailplay_type);
	mux->inst.fd = &sailplay_usb_func;
	mux->inst.free_func_inst = sailplay_free_inst;
	spin_lock_init(&mux->in_lock);
	spin_lock_init(&mux->out_lock);
	init_waitqueue_head(&mux->in_wait);
	init_waitqueue_head(&mux->out_wait);

	return &mux->inst;

err_out_buf:
	kfree(mux->out_buf);
err_in_buf:
	kfree(mux->in_buf);
err_cdev:
	cdev_del(&mux->cdev);
err_idr:
	idr_remove(&sailplay_idr, minor);
err_free_mux:
	kfree(mux);
	return ERR_PTR(rc);
}

static struct usb_function *sailplay_alloc_func(struct usb_function_instance *inst)
{
	struct sailplay_mux *mux = to_mux_inst(inst);

	mux->func.name = sailplay_usb_func.name;
	mux->func.strings = mux->string_tabs;
	mux->func.bind = sailplay_bind;
	mux->func.unbind = sailplay_unbind;
	mux->func.set_alt = sailplay_set_alt;
	mux->func.disable = sailplay_disable;
	mux->func.suspend = sailplay_suspend;
	mux->func.resume = sailplay_resume;
	mux->func.free_func = sailplay_free_func;
	mux->func.mod = THIS_MODULE;

	return &mux->func;
}

static int __init sailplay_usbmux_init(void)
{
	int rc;

	sailplay_class = class_create(THIS_MODULE, SAILPLAY_CLASS);
	if (IS_ERR(sailplay_class))
		return PTR_ERR(sailplay_class);

	rc = alloc_chrdev_region(&sailplay_dev, 0, SAILPLAY_MINORS, SAILPLAY_CLASS);
	if (rc)
		goto err_class;

	sailplay_usb_func.alloc_inst = sailplay_alloc_inst;
	sailplay_usb_func.alloc_func = sailplay_alloc_func;

	return usb_function_register(&sailplay_usb_func);
err_class:
	class_destroy(sailplay_class);
	sailplay_class = NULL;
	return rc;
}

static void __exit sailplay_usbmux_exit(void)
{
	usb_function_unregister(&sailplay_usb_func);
	idr_destroy(&sailplay_idr);
	unregister_chrdev_region(sailplay_dev, SAILPLAY_MINORS);
	class_destroy(sailplay_class);
}

module_init(sailplay_usbmux_init);
module_exit(sailplay_usbmux_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Minimal USBMUX function for CarPlay probing");
