QT += quick qml dbus network
CONFIG += console c++14 sailfishapp
TEMPLATE = app
TARGET = sailplay-communication
SOURCES += main.cpp backend.cpp ../carui/contenthost.cpp
HEADERS += backend.h ../carui/contenthost.h
INCLUDEPATH += ../carui
include(../../sdk/qt/sailplay-sdk.pri)
