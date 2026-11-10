QT += core dbus
CONFIG += c++11
INCLUDEPATH += $$PWD $$OUT_PWD
HEADERS += $$PWD/sailplaysession.h $$PWD/sailplayapplication.h
SOURCES += $$PWD/sailplaysession.cpp $$PWD/sailplayapplication.cpp

isEmpty(SAILPLAY_SDK_INTERFACES) {
    SAILPLAY_SDK_INTERFACES = $$clean_path($$PWD/../../sailplay_sdk/interfaces)
    !exists($$SAILPLAY_SDK_INTERFACES/org.sailplay.App1.xml) {
        SAILPLAY_SDK_INTERFACES = /usr/share/dbus-1/interfaces
    }
}
DBUS_INTERFACES += $$SAILPLAY_SDK_INTERFACES/org.sailplay.App1.xml \
                   $$SAILPLAY_SDK_INTERFACES/org.sailplay.Session1.xml \
                   $$SAILPLAY_SDK_INTERFACES/org.sailplay.Navigation1.xml
