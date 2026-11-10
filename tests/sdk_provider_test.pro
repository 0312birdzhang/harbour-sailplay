QT += core dbus
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-sdk-provider-test
SOURCES += sdk_provider_test.cpp ../display-source/carui/musichost.cpp
HEADERS += ../display-source/carui/musichost.h
INCLUDEPATH += ../display-source/carui
include(../sdk/qt/sailplay-sdk.pri)
