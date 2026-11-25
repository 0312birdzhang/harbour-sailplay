#ifndef SAILPLAY_CONTENT_H
#define SAILPLAY_CONTENT_H

#include <QVariantMap>

namespace SailplayContent {
QVariant decode(const QVariant &value);
QVariantMap page(const QString &id = QStringLiteral("root"), const QString &title = QString());
QVariantMap item(const QString &id, const QString &title, const QString &kind = QStringLiteral("folder"),
                 const QString &action = QString(), const QVariantMap &parameters = QVariantMap());
// Optional presentation hints travel beside a page: under "presentation" in a
// query result and under "contentPresentation" in the state for the root page.
// Layouts are "list", "grid", "wide" and "split"; playback is "unplayed",
// "started", "playing" or "finished"; an image is an absolute file or an
// http(s) address; side names a folder the host keeps in a panel (root only).
QVariantMap presentation(const QString &layout = QString(), bool tabs = false, const QString &side = QString());
bool hint(QVariantMap &presentation, const QString &itemId, const QString &image,
          const QString &playback = QString());
QVariantMap cleanPresentation(const QVariant &value, const QVariantMap &page);
QVariantList presentedItems(const QVariantList &items, const QVariantMap &presentation);
bool validPage(const QVariantMap &page);
bool validRoot(const QVariantMap &page);
bool validQuery(const QVariantMap &parameters, bool search);
}

#endif
