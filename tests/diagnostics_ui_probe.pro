QT += quick qml dbus network testlib
CONFIG += console c++14 sailfishapp
TEMPLATE = app
TARGET = sailplay-diagnostics-ui-probe
SOURCES += diagnostics_ui_probe.cpp \
           ../display-source/carui/navigationhost.cpp \
           ../display-source/carui/musichost.cpp \
           ../display-source/carui/contenthost.cpp \
           ../display-source/carui/mapcanvas.cpp \
           ../display-source/carui/diagnosticslogging.cpp
HEADERS += ../display-source/carui/navigationhost.h \
           ../display-source/carui/musichost.h \
           ../display-source/carui/contenthost.h \
           ../display-source/carui/mapcanvas.h \
           ../display-source/carui/diagnosticslogging.h
INCLUDEPATH += $$OUT_PWD ../display-source/carui
include(../sdk/qt/sailplay-sdk.pri)

CONTROLLER_SOURCE = $$PWD/../display-source/carui/main.cpp
controller_moc.input = CONTROLLER_SOURCE
controller_moc.output = main.moc
controller_moc.commands = $$[QT_HOST_BINS]/moc ${QMAKE_FILE_IN} -o ${QMAKE_FILE_OUT}
controller_moc.CONFIG += no_link target_predeps
QMAKE_EXTRA_COMPILERS += controller_moc
