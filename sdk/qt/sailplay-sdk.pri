QT += core dbus
CONFIG += c++11
INCLUDEPATH += $$PWD $$OUT_PWD
HEADERS += $$PWD/sailplaysession.h $$PWD/sailplayapplication.h $$PWD/sailplayprovider.h
SOURCES += $$PWD/sailplaysession.cpp $$PWD/sailplayapplication.cpp $$PWD/sailplayprovider.cpp
HEADERS += $$PWD/sailplayrenderer.h
SOURCES += $$PWD/sailplayrenderer.cpp
HEADERS += $$PWD/sailplaycontent.h
SOURCES += $$PWD/sailplaycontent.cpp

isEmpty(SAILPLAY_SDK_INTERFACES) {
    SAILPLAY_SDK_INTERFACES = $$clean_path($$PWD/../../sailplay_sdk/interfaces)
    !exists($$SAILPLAY_SDK_INTERFACES/org.sailplay.App1.xml) {
        SAILPLAY_SDK_INTERFACES = /usr/share/dbus-1/interfaces
    }
}
DBUS_INTERFACES += $$SAILPLAY_SDK_INTERFACES/org.sailplay.App1.xml \
                   $$SAILPLAY_SDK_INTERFACES/org.sailplay.Session1.xml \
                   $$SAILPLAY_SDK_INTERFACES/org.sailplay.Navigation1.xml \
                   $$SAILPLAY_SDK_INTERFACES/org.sailplay.Content1.xml

sailplay_contracts.files = $$SAILPLAY_SDK_INTERFACES/org.sailplay.App1.xml \
                          $$SAILPLAY_SDK_INTERFACES/org.sailplay.Session1.xml \
                          $$SAILPLAY_SDK_INTERFACES/org.sailplay.Navigation1.xml \
                          $$SAILPLAY_SDK_INTERFACES/org.sailplay.Content1.xml
sailplay_contracts.prefix = /sailplay-sdk/interfaces
sailplay_contracts.base = $$SAILPLAY_SDK_INTERFACES
RESOURCES += sailplay_contracts
