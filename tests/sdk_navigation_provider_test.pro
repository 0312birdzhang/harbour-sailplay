QT += core dbus
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-sdk-navigation-provider-test
SOURCES += sdk_navigation_provider_test.cpp
include(../sdk/qt/sailplay-sdk.pri)
