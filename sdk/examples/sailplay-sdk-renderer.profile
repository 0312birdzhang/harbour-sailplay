# Dedicated renderers connect to the host's Wayland socket and receive input
# through that connection. The host's input-injection endpoint stays private.
whitelist ${RUNUSER}/imira-comp-0
read-only ${RUNUSER}/imira-comp-0

dbus-user.own org.sailplay.Client.*
dbus-user.talk org.example.SailplayCounter
