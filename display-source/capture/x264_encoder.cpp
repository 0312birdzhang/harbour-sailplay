/*
 * x264_encoder.cpp — software H.264 encoder via x264.
 */
#include "x264_encoder.h"

#include <cstring>
#include <cstdio>

#include "x264.h"

bool X264Encoder::init(int width, int height, int fps, int bitrate,
                       const OutputCallback &cb)
{
    m_cb = cb;
    m_width = width;
    m_height = height;

    x264_param_t param;
    if (x264_param_default_preset(&param, "ultrafast", "zerolatency") < 0) {
        m_error = "x264_param_default_preset failed";
        return false;
    }
    param.i_width = width;
    param.i_height = height;
    param.i_fps_num = fps;
    param.i_fps_den = 1;
    param.i_threads = 2;
    param.i_csp = X264_CSP_I420;
    param.rc.i_rc_method = X264_RC_ABR;
    param.rc.i_bitrate = bitrate / 1000;
    /* Bound the per-frame size. On high-detail content (browser pages) an
     * unconstrained IDR balloons to ~470KB, which overruns the head unit's
     * decode buffer and kills the session right at the first video frame.
     * VBV with a 4-frame buffer caps one AU at ~bitrate/fps*4 (~66KB at
     * 4Mbps/30fps) and makes rate control spread the rest over the GOP. */
    param.rc.i_vbv_max_bitrate = bitrate / 1000;
    param.rc.i_vbv_buffer_size = bitrate / 1000 * 4 / fps + 1;
    param.i_keyint_max = fps / 2;  /* 0.5s GOP: fast resync */
    param.i_keyint_min = 1;
    param.b_open_gop = 0;           /* closed GOP: IDR frames */
    param.b_repeat_headers = 1;   /* SPS/PPS in stream (Annex-B) */
    param.b_annexb = 1;
    if (x264_param_apply_profile(&param, "baseline") < 0) {
        m_error = "x264 profile baseline failed";
        return false;
    }
    /* apply_profile may reset the GOP settings — re-assert closed GOP so
     * the stream starts with a real IDR slice (type 5); the head unit's
     * decoder refuses to start on an open-GOP I/P frame (black screen). */
    param.b_open_gop = 0;
    param.i_keyint_max = fps / 2;
    param.i_keyint_min = 1;

    m_enc = x264_encoder_open(&param);
    if (!m_enc) {
        m_error = "x264_encoder_open failed";
        return false;
    }
    m_pic = new x264_picture_t;
    if (x264_picture_alloc(m_pic, param.i_csp, width, height) < 0) {
        m_error = "x264_picture_alloc failed";
        x264_encoder_close(m_enc);
        m_enc = nullptr;
        return false;
    }
    m_pic->i_pts = 0;
    fprintf(stderr, "x264 cfg: open_gop=%d keyint_max=%d keyint_min=%d fps=%d threads=%d "
                    "vbv_max=%d vbv_buf=%d\n",
            param.b_open_gop, param.i_keyint_max, param.i_keyint_min, fps, param.i_threads,
            param.rc.i_vbv_max_bitrate, param.rc.i_vbv_buffer_size);
    return true;
}

bool X264Encoder::encode(const uint8_t *i420, size_t size)
{
    if (!m_enc)
        return false;
    size_t ysz = (size_t)m_width * m_height;
    size_t uvsz = ysz / 4;
    if (size < ysz + 2 * uvsz)
        return false;
    memcpy(m_pic->img.plane[0], i420, ysz);
    memcpy(m_pic->img.plane[1], i420 + ysz, uvsz);
    memcpy(m_pic->img.plane[2], i420 + ysz + uvsz, uvsz);
    m_pic->i_pts = m_pts++;

    x264_nal_t *nals = nullptr;
    int i_nals = 0;
    x264_picture_t pic_out;
    int sz = x264_encoder_encode(m_enc, &nals, &i_nals, m_pic, &pic_out);
    if (sz < 0) {
        m_error = "x264_encoder_encode failed";
        return false;
    }
    if (sz > 0 && m_cb && nals) {
        for (int i = 0; i < i_nals; i++) {
            bool idr = (nals[i].i_type == NAL_SLICE_IDR);
            fprintf(stderr, "cap NAL type=%d size=%d\n", nals[i].i_type, nals[i].i_payload);
            m_cb(nals[i].p_payload, nals[i].i_payload, idr);
        }
    }
    return true;
}

void X264Encoder::stop()
{
    if (m_enc) {
        x264_nal_t *nals = nullptr;
        int i_nals = 0;
        x264_picture_t pic_out;
        while (x264_encoder_delayed_frames(m_enc) > 0) {
            int sz = x264_encoder_encode(m_enc, &nals, &i_nals, nullptr, &pic_out);
            if (sz <= 0) break;
            if (m_cb && nals) {
                for (int i = 0; i < i_nals; i++)
                    m_cb(nals[i].p_payload, nals[i].i_payload,
                         nals[i].i_type == NAL_SLICE_IDR);
            }
        }
        if (m_pic) {
            x264_picture_clean(m_pic);
            delete m_pic;
            m_pic = nullptr;
        }
        x264_encoder_close(m_enc);
        m_enc = nullptr;
    }
}