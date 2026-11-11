#ifndef SAILPLAY_CONTENT_H
#define SAILPLAY_CONTENT_H

#include <QVariantMap>

namespace SailplayContent {
QVariant decode(const QVariant &value);
QVariantMap page(const QString &id = QStringLiteral("root"), const QString &title = QString());
QVariantMap item(const QString &id, const QString &title, const QString &kind = QStringLiteral("folder"),
                 const QString &action = QString(), const QVariantMap &parameters = QVariantMap());
bool validPage(const QVariantMap &page);
bool validRoot(const QVariantMap &page);
bool validQuery(const QVariantMap &parameters, bool search);
}

#endif
