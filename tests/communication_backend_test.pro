QT += qml dbus
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-communication-backend-test
SOURCES += communication_backend_test.cpp ../display-source/communication/backend.cpp
HEADERS += ../display-source/communication/backend.h
include(../sdk/qt/sailplay-sdk.pri)
