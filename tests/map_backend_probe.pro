QT += core dbus gui qml quick
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-map-backend-probe
isEmpty(ORGANICMAPS_ROOT) {
    ORGANICMAPS_ROOT = $$clean_path($$PWD/../../organicmaps-sailfish)
}
INCLUDEPATH += $$ORGANICMAPS_ROOT
SOURCES += map_backend_probe.cpp \
           $$ORGANICMAPS_ROOT/sailfish/map_surface.cpp \
           $$ORGANICMAPS_ROOT/sailfish/sailplay_navigation.cpp \
           $$ORGANICMAPS_ROOT/sailfish/navigation_export.cpp
HEADERS += $$ORGANICMAPS_ROOT/sailfish/map_surface.hpp \
           $$ORGANICMAPS_ROOT/sailfish/navigation_export.hpp
include(../sdk/qt/sailplay-sdk.pri)
