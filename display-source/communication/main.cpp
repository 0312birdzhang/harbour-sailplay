#include "backend.h"
#include "contenthost.h"
#include "sailplayrenderer.h"
#include "sailplaycontent.h"
#include <QCoreApplication>
#include <QGuiApplication>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickView>
#include <QTranslator>
#include <QLocale>
#include <sailfishapp.h>
#include <cstdio>
#include <csignal>

namespace {
void translation(QTranslator &translator, QCoreApplication &app)
{
    if (translator.load(QLocale(), QStringLiteral("sailplay"), QStringLiteral("_"),
                        QStringLiteral("/opt/sailplay/carui/translations"))) app.installTranslator(&translator);
}

QObject *load(QQmlEngine &engine, const QString &filename)
{
    QQmlComponent component(&engine, QUrl::fromLocalFile(QStringLiteral("/opt/sailplay/communication/") + filename));
    QObject *object = component.create();
    if (!object) {
        for (const QQmlError &error : component.errors()) fprintf(stderr, "%s\n", qPrintable(error.toString()));
    }
    return object;
}
}

int main(int argc, char **argv)
{
    signal(SIGPIPE, SIG_IGN);
    const bool backendMode = argc == 3 && QByteArray(argv[1]) == QByteArray("--backend");
    if (backendMode) {
        const QString kind = QString::fromLocal8Bit(argv[2]);
        if (kind != QStringLiteral("phone") && kind != QStringLiteral("messages")) return 2;
        qputenv("QT_QPA_PLATFORM", "minimal");
        qputenv("QT_IM_MODULE", "none");
        QGuiApplication app(argc, argv);
        app.setQuitOnLastWindowClosed(false);
        app.setOrganizationName(QStringLiteral("org.sailplay"));
        app.setApplicationName(QStringLiteral("System") + kind);
        QTranslator translator;
        translation(translator, app);
        QQmlEngine engine;
        QObject *models = load(engine, QStringLiteral("models.qml"));
        if (!models) return 1;
        models->setParent(&engine);
        CommunicationBackend backend(kind, models);
        if (!backend.start()) return 1;
        return app.exec();
    }
    const QString service = QString::fromUtf8(qgetenv("SAILPLAY_RENDERER_SERVICE"));
    const bool phone = service == QStringLiteral("org.sailplay.System.Phone");
    if (!phone && service != QStringLiteral("org.sailplay.System.Messages")) return 2;
    qputenv("QT_IM_MODULE", "Maliit");
    qputenv("MALIIT_SERVER_ADDRESS", "unix:path=/run/user/100000/sailplay-maliit/socket");
    QGuiApplication app(argc, argv);
    app.setOrganizationName(QStringLiteral("org.sailplay"));
    app.setApplicationName(phone ? QStringLiteral("PhoneRenderer") : QStringLiteral("MessagesRenderer"));
    QTranslator translator;
    translation(translator, app);
    SailplayRenderer renderer;
    SailplayContentHost browser;
    SailplayApplication declaration;
    declaration.valid = true;
    declaration.applicationId = phone ? QStringLiteral("sailplay-phone") : QStringLiteral("sailplay-messages");
    declaration.desktopId = declaration.applicationId;
    declaration.service = service;
    declaration.path = QStringLiteral("/org/sailplay/v1/App");
    declaration.presentation = QStringLiteral("template");
    declaration.capabilities << QStringLiteral("content");
    browser.open(declaration, QCoreApplication::translate("Sailplay", phone ? "Phone" : "Messages"));
    QObject::connect(&renderer, &SailplayRenderer::activeChanged, &browser, [&]() { browser.setActive(renderer.active()); });
    QObject::connect(&renderer, &SailplayRenderer::closed, &app, &QCoreApplication::quit);
    QObject::connect(&app, &QCoreApplication::aboutToQuit, &browser, &SailplayContentHost::close);
    if (!renderer.start()) return 1;
    QQuickView *themeView = SailfishApp::createView();
    QQmlEngine &engine = *themeView->engine();
    engine.rootContext()->setContextProperty(QStringLiteral("renderer"), &renderer);
    engine.rootContext()->setContextProperty(QStringLiteral("browser"), &browser);
    engine.rootContext()->setContextProperty(QStringLiteral("phoneApp"), phone);
    const auto updateState = [&]() {
        engine.rootContext()->setContextProperty(QStringLiteral("communicationState"), SailplayContent::decode(renderer.state()));
    };
    updateState();
    QObject::connect(&renderer, &SailplayRenderer::stateChanged, &engine, updateState);
    QObject *window = load(engine, QStringLiteral("Communication.qml"));
    if (!window) { delete themeView; return 1; }
    const int result = app.exec();
    delete window;
    delete themeView;
    return result;
}
