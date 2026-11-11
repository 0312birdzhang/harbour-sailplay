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
