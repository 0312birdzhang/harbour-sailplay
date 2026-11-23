#include "sailplaycontent.h"

#include <QDBusArgument>
#include <QDBusVariant>
#include <QSet>
#include <QVector>

namespace {
bool text(const QVariant &value, int limit = 1024, bool required = false)
{
    const QString string = value.toString();
    return value.type() == QVariant::String && string.toUcs4().size() <= limit
        && !string.contains(QChar::Null) && (!required || !string.isEmpty());
}

bool integer(const QVariant &value, qulonglong maximum = 0xffffffff)
{
    return (value.type() == QVariant::UInt || value.type() == QVariant::ULongLong
        || ((value.type() == QVariant::Int || value.type() == QVariant::LongLong) && value.toLongLong() >= 0))
        && value.toULongLong() <= maximum;
}

bool keys(const QVariantMap &value, const QStringList &expected)
{
    return QSet<QString>::fromList(value.keys()) == QSet<QString>::fromList(expected);
}

bool validItem(const QVariantMap &value)
{
    if (!keys(value, {"id", "title", "subtitle", "kind", "action", "parameters", "enabled"})
        || !text(value.value("id"), 256, true) || !text(value.value("title"), 1024, true)
        || !text(value.value("subtitle")) || !text(value.value("action"), 256)
        || !text(value.value("kind"), 256, true)
        || value.value("parameters").type() != QVariant::Map || value.value("enabled").type() != QVariant::Bool)
        return false;
    const QString kind = value.value("kind").toString();
    return (kind == QStringLiteral("folder") && value.value("action").toString().isEmpty())
        || (kind == QStringLiteral("action") && !value.value("action").toString().isEmpty());
}
}

QVariant SailplayContent::decode(const QVariant &value)
{
    if (value.userType() == qMetaTypeId<QDBusVariant>())
        return decode(qvariant_cast<QDBusVariant>(value).variant());
    if (value.userType() == qMetaTypeId<QDBusArgument>()) {
        const QDBusArgument argument = qvariant_cast<QDBusArgument>(value);
        if (argument.currentSignature() == QStringLiteral("a{sv}"))
            return decode(qdbus_cast<QVariantMap>(value));
        if (argument.currentSignature() == QStringLiteral("aa{sv}")) {
            QVariantList items;
            argument.beginArray();
            while (!argument.atEnd()) {
                QVariantMap entry;
                argument >> entry;
                items.append(decode(entry));
            }
            argument.endArray();
            return items;
        }
        if (argument.currentSignature() == QStringLiteral("av"))
            return decode(qdbus_cast<QVariantList>(value));
    }
    if (value.type() == QVariant::Map) {
        QVariantMap result = value.toMap();
        for (auto entry = result.begin(); entry != result.end(); ++entry) entry.value() = decode(entry.value());
        return result;
    }
    if (value.type() == QVariant::List) {
        QVariantList result;
        for (const QVariant &entry : value.toList()) result.append(decode(entry));
        return result;
    }
    return value;
}

namespace {
const QStringList layouts = {QStringLiteral("list"), QStringLiteral("grid"), QStringLiteral("wide"),
                             QStringLiteral("split")};
const QStringList playbackStates = {QStringLiteral("unplayed"), QStringLiteral("started"),
                                    QStringLiteral("playing"), QStringLiteral("finished")};

bool validImage(const QVariant &value)
{
    if (!text(value, 2048, true)) return false;
    const QString image = value.toString();
    for (const QChar character : image) if (character.unicode() < 32) return false;
    return image.startsWith(QLatin1Char('/')) || image.startsWith(QStringLiteral("file:///"))
        || image.startsWith(QStringLiteral("https://")) || image.startsWith(QStringLiteral("http://"));
}
}

QVariantMap SailplayContent::presentation(const QString &layout, bool tabs, const QString &side)
{
    QVariantMap result;
    if (layouts.contains(layout)) result.insert(QStringLiteral("layout"), layout);
    if (tabs) result.insert(QStringLiteral("tabs"), true);
    if (text(side, 256, true)) result.insert(QStringLiteral("side"), side);
    return result;
}

bool SailplayContent::hint(QVariantMap &presentation, const QString &itemId, const QString &image,
                           const QString &playback)
{
    if ((!image.isEmpty() && !validImage(image)) || (!playback.isEmpty() && !playbackStates.contains(playback))
        || !text(itemId, 256, true)) return false;
    QVariantMap entry;
    if (!image.isEmpty()) entry.insert(QStringLiteral("image"), image);
    if (!playback.isEmpty()) entry.insert(QStringLiteral("playback"), playback);
    if (entry.isEmpty()) return true;
    QVariantMap items = presentation.value(QStringLiteral("items")).toMap();
    items.insert(itemId, entry);
    presentation.insert(QStringLiteral("items"), items);
    return true;
}

// Hosts keep what they can use and never reject a page for its presentation.
QVariantMap SailplayContent::cleanPresentation(const QVariant &value, const QVariantMap &page)
{
    QVariantMap result;
    const QVariant decoded = decode(value);
    if (decoded.type() != QVariant::Map) return result;
    const QVariantMap source = decoded.toMap();
    const QVariant layout = source.value(QStringLiteral("layout"));
    if (layout.type() == QVariant::String && layouts.contains(layout.toString()))
        result.insert(QStringLiteral("layout"), layout.toString());
    const QVariant tabs = source.value(QStringLiteral("tabs"));
    if (tabs.type() == QVariant::Bool && tabs.toBool()) result.insert(QStringLiteral("tabs"), true);
    if (text(source.value(QStringLiteral("side")), 256, true))
        result.insert(QStringLiteral("side"), source.value(QStringLiteral("side")).toString());
    if (source.value(QStringLiteral("items")).type() != QVariant::Map) return result;
    const QVariantMap entries = source.value(QStringLiteral("items")).toMap();
    QVariantMap hints;
    for (const QVariant &row : page.value(QStringLiteral("items")).toList()) {
        const QString id = row.toMap().value(QStringLiteral("id")).toString();
        if (entries.value(id).type() != QVariant::Map) continue;
        const QVariantMap entry = entries.value(id).toMap();
        QVariantMap kept;
        if (validImage(entry.value(QStringLiteral("image"))))
            kept.insert(QStringLiteral("image"), entry.value(QStringLiteral("image")).toString());
        const QVariant playback = entry.value(QStringLiteral("playback"));
        if (playback.type() == QVariant::String && playbackStates.contains(playback.toString()))
            kept.insert(QStringLiteral("playback"), playback.toString());
        if (!kept.isEmpty()) hints.insert(id, kept);
    }
    if (!hints.isEmpty()) result.insert(QStringLiteral("items"), hints);
    return result;
}

// Rows for display: each one with the "image" and "playback" of its hints, empty when absent.
QVariantList SailplayContent::presentedItems(const QVariantList &items, const QVariantMap &presentation)
{
    const QVariantMap hints = presentation.value(QStringLiteral("items")).toMap();
    QVariantList result;
    for (const QVariant &row : items) {
        QVariantMap item = row.toMap();
        const QVariantMap entry = hints.value(item.value(QStringLiteral("id")).toString()).toMap();
        item.insert(QStringLiteral("image"), entry.value(QStringLiteral("image")).toString());
        item.insert(QStringLiteral("playback"), entry.value(QStringLiteral("playback")).toString());
        result.append(item);
    }
    return result;
}

QVariantMap SailplayContent::page(const QString &id, const QString &title)
{
    return {{"id", id}, {"title", title}, {"version", qulonglong(1)}, {"items", QVariantList()}, {"actions", QVariantList()},
        {"searchEnabled", false}, {"message", QString()}, {"messageKind", QStringLiteral("none")},
        {"offset", uint(0)}, {"hasMore", false}};
}

QVariantMap SailplayContent::item(const QString &id, const QString &title, const QString &kind,
                                const QString &action, const QVariantMap &parameters)
{
    return {{"id", id}, {"title", title}, {"subtitle", QString()}, {"kind", kind}, {"action", action},
        {"parameters", parameters}, {"enabled", true}};
}

bool SailplayContent::validPage(const QVariantMap &value)
{
    if (!keys(value, {"id", "title", "version", "items", "actions", "searchEnabled", "message", "messageKind", "offset", "hasMore"})
        || !text(value.value("id"), 256, true) || !text(value.value("title")) || !text(value.value("message"))
        || value.value("messageKind").type() != QVariant::String
        || !QStringList{"none", "info", "warning", "error"}.contains(value.value("messageKind").toString())
        || value.value("searchEnabled").type() != QVariant::Bool || value.value("hasMore").type() != QVariant::Bool
        || !integer(value.value("offset")) || !integer(value.value("version"), Q_UINT64_C(0xffffffffffffffff))) return false;
    for (const QString &key : {QStringLiteral("items"), QStringLiteral("actions")}) {
        if (value.value(key).type() != QVariant::List) return false;
        const QVariantList entries = value.value(key).toList();
        if (entries.size() > (key == QStringLiteral("items") ? 50 : 4)) return false;
        QSet<QString> ids;
        for (const QVariant &entry : entries) {
            if (entry.type() != QVariant::Map || !validItem(entry.toMap())) return false;
            const QVariantMap item = entry.toMap();
            if (ids.contains(item.value("id").toString())
                || (key == QStringLiteral("actions") && item.value("kind") != QStringLiteral("action"))) return false;
            ids.insert(item.value("id").toString());
        }
    }
    const int count = value.value("items").toList().size();
    return !value.value("hasMore").toBool() || (count > 0 && value.value("offset").toULongLong() + count <= 0xffffffff);
}

bool SailplayContent::validQuery(const QVariantMap &value, bool search)
{
    QStringList fields = {"id", "offset", "limit"};
    if (search) fields.append(QStringLiteral("query"));
    return keys(value, fields) && text(value.value("id"), 256, true) && integer(value.value("offset"))
        && integer(value.value("limit")) && value.value("limit").toUInt() >= 1 && value.value("limit").toUInt() <= 50
        && (!search || text(value.value("query"), 256, true));
}

bool SailplayContent::validRoot(const QVariantMap &value)
{
    return validPage(value) && value.value("id") == QStringLiteral("root") && value.value("offset").toUInt() == 0;
}
