#include "sailplaysession.h"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>
#include <cstdio>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    SailplaySession session;
    const QString service = app.arguments().value(1, QStringLiteral("org.example.SailplayCounter"));
    QObject::connect(&session, &SailplaySession::readyChanged, &app, [&](bool ready) {
        if (ready) session.invoke(QStringLiteral("increment"),
                                  {{QStringLiteral("amount"), qint64(1)}}, session.revision());
    });
    QObject::connect(&session, &SailplaySession::requestFinished, &app,
        [&](qulonglong request, qulonglong revision, const QVariantMap &result,
            const QString &name, const QString &message) {
            QVariantMap output = {{QStringLiteral("request"), QVariant::fromValue(request)},
                {QStringLiteral("revision"), QVariant::fromValue(revision)},
                {QStringLiteral("result"), result}, {QStringLiteral("error"), name},
                {QStringLiteral("message"), message}};
            puts(QJsonDocument::fromVariant(output).toJson(QJsonDocument::Compact).constData());
            session.close();
            app.exit(name.isEmpty() ? 0 : 1);
        });
    QObject::connect(&session, &SailplaySession::errorOccurred, &app,
        [&](const QString &name, const QString &message) {
            fprintf(stderr, "%s %s\n", qPrintable(name), qPrintable(message));
            app.exit(1);
        });
    QTimer::singleShot(10000, &app, [&]() { app.exit(2); });
    session.open(service);
    return app.exec();
}
