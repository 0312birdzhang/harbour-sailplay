import dbus,json

b=dbus.SystemBus();m=dbus.Interface(b.get_object('net.connman','/'),'net.connman.Manager')
for p,v in m.GetServices():
 if str(v.get('Name','')).startswith('Smartphone_connect_'):
  print({k:str(v.get(k)) for k in ('State','Error','Strength','Ethernet','IPv4.Configuration','IPv6.Configuration','Nameservers')})