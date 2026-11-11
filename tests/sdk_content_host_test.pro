QT += quick qml dbus
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-sdk-content-host-test
SOURCES += sdk_content_host_test.cpp ../display-source/carui/contenthost.cpp
HEADERS += ../display-source/carui/contenthost.h
include(../sdk/qt/sailplay-sdk.pri)
