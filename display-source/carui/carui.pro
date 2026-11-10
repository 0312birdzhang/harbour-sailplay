QT += quick qml dbus network
CONFIG += console c++14 sailfishapp
TEMPLATE = app
TARGET = carui
SOURCES += main.cpp navigationhost.cpp
HEADERS += navigationhost.h
include(../../sdk/qt/sailplay-sdk.pri)
