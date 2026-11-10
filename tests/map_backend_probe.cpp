#include "sailfish/map_surface.hpp"
#include "sailfish/navigation_export.hpp"
#include "sailfish/sailplay_navigation.hpp"
#include "sailplayprovider.h"

#include <QGuiApplication>
#include <QJsonObject>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickWindow>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "MAP_BACKEND_CHECK_FAILED line=%d %s\n", __LINE__, #condition); std::exit(1); } } while (false)

int main(int argc, char **argv)
{
    QGuiApplication application(argc, argv);
    qmlRegisterType<sailfish::MapSurface>("Sailplay.MapProbe", 1, 0, "MapSurface");
    QObject backendOwner;
    auto core = std::unique_ptr<QQuickItem>(new QQuickItem);
    core->setParent(&backendOwner);
    QQmlEngine::setObjectOwnership(core.get(), QQmlEngine::CppOwnership);
    for (int cycle = 0; cycle < 3; ++cycle) {
        QQmlEngine engine;
        engine.rootContext()->setContextProperty(QStringLiteral("mapCore"), core.get());
        QQmlComponent component(&engine);
        component.setData("import QtQuick 2.6\nimport Sailplay.MapProbe 1.0\nMapSurface { width: 720; height: 320; map: mapCore }", QUrl());
        std::unique_ptr<QObject> root(component.create());
        CHECK(root && component.errors().isEmpty());
        auto surface = qobject_cast<QQuickItem *>(root.get());
        CHECK(core->parentItem() == surface && core->parent() == &backendOwner);
        CHECK(QSizeF(core->width(), core->height()) == QSizeF(720, 320));
        surface->setSize(QSizeF(1138, 688));
        CHECK(QSizeF(core->width(), core->height()) == QSizeF(1138, 688));
        QQuickWindow window;
        surface->setParentItem(window.contentItem());
        CHECK(core->window() == &window);
        root.reset();
        CHECK(core->parentItem() == nullptr && core->window() == nullptr);
        CHECK(core->parent() == &backendOwner);
    }
    {
        sailfish::MapSurface surface;
        auto item = std::unique_ptr<QQuickItem>(new QQuickItem);
        surface.setMap(item.get());
        item.reset();
        CHECK(surface.map() == nullptr);
    }
    qunsetenv("SAILPLAY_NAVIGATION_EXPORT");
    sailfish::NavigationExport exporter;
    int changes = 0;
    QObject::connect(&exporter, &sailfish::NavigationExport::changed, [&] { ++changes; });
    CHECK(exporter.Snapshot().value("state").toString() == QStringLiteral("idle"));
    exporter.Publish({{"state", "stopped"}});
    CHECK(changes == 1 && exporter.Snapshot().value("state").toString() == QStringLiteral("stopped"));
    QJsonObject raw = {{"state", "active"}, {"routerType", 0}, {"turn", 0}, {"pedestrianTurn", 0},
        {"exitNumber", 3}, {"remainingSeconds", 900}, {"nextDistance", 2.5}, {"nextDistanceUnit", 0},
        {"remainingDistance", 3.5}, {"remainingDistanceUnit", 0}, {"currentRoad", "Current"},
        {"nextRoad", "Next"}, {"destination", "Destination"}};
    QStringList const expectedTurns = {"unknown", "continue", "turn-right", "sharp-right", "slight-right",
        "turn-left", "sharp-left", "slight-left", "uturn", "uturn", "roundabout-enter", "roundabout-exit",
        "roundabout-continue", "unknown", "arrive", "exit-left", "exit-right"};
    for (int turn = 0; turn < expectedTurns.size(); ++turn) {
        raw["turn"] = turn;
        auto guidance = sailfish::SailplayGuidance(raw);
        CHECK(guidance.value(QStringLiteral("maneuver")) == expectedTurns.at(turn));
        CHECK(guidance.value(QStringLiteral("drivingSide")) == (turn == 9 ? QStringLiteral("left") : QStringLiteral("right")));
        SailplayProvider provider(QStringLiteral("map"), {{QStringLiteral("navigation"), guidance}}, {QStringLiteral("navigation")});
        provider.setActionHandler(QStringLiteral("navigation.stop"), [](qulonglong, const QVariantMap &) {});
        CHECK(provider.start());
    }
    QStringList const modes = {"driving", "walking", "cycling", "transit"};
    for (int mode = 0; mode < modes.size(); ++mode) {
        raw["routerType"] = mode;
        CHECK(sailfish::SailplayGuidance(raw).value(QStringLiteral("mode")) == modes.at(mode));
    }
    QStringList const pedestrianTurns = {"unknown", "continue", "turn-right", "turn-left", "arrive"};
    raw["routerType"] = 1;
    for (int turn = 0; turn < pedestrianTurns.size(); ++turn) {
        raw["pedestrianTurn"] = turn;
        CHECK(sailfish::SailplayGuidance(raw).value(QStringLiteral("maneuver")) == pedestrianTurns.at(turn));
    }
    double const factors[] = {1, 1000, 0.3048, 1609.344};
    for (int unit = 0; unit < 4; ++unit) {
        raw["nextDistanceUnit"] = unit;
        raw["remainingDistanceUnit"] = unit;
        auto const guidance = sailfish::SailplayGuidance(raw);
        CHECK(std::abs(guidance.value(QStringLiteral("nextDistanceMeters")).toDouble() - 2.5 * factors[unit]) < 1e-7);
        CHECK(std::abs(guidance.value(QStringLiteral("remainingDistanceMeters")).toDouble() - 3.5 * factors[unit]) < 1e-7);
        CHECK(guidance.value(QStringLiteral("exitNumber")).type() == QVariant::UInt);
        CHECK(guidance.value(QStringLiteral("remainingSeconds")).type() == QVariant::ULongLong);
        CHECK(guidance.value(QStringLiteral("updatedMs")).type() == QVariant::ULongLong);
    }
    raw["currentRoad"] = QString::fromUtf8("道路 🌍");
    CHECK(sailfish::SailplayGuidance(raw).value(QStringLiteral("currentRoad")) == QString::fromUtf8("道路 🌍"));
    QString const emoji = QString::fromUtf8("🌍");
    raw["destination"] = emoji.repeated(1025) + QChar::Null;
    CHECK(sailfish::SailplayGuidance(raw).value(QStringLiteral("destination")) == emoji.repeated(1024));
    for (const auto &state : {QStringLiteral("idle"), QStringLiteral("stopped"), QStringLiteral("arrived"), QStringLiteral("unavailable")}) {
        raw["state"] = state;
        const auto guidance = sailfish::SailplayGuidance(raw);
        CHECK(guidance.value(QStringLiteral("state")) == state);
        CHECK(guidance.value(QStringLiteral("currentRoad")).toString().isEmpty());
        CHECK(guidance.value(QStringLiteral("remainingDistanceMeters")).toDouble() == 0);
        CHECK(guidance.value(QStringLiteral("maneuver")) == QStringLiteral("unknown"));
    }
    puts("MAP_BACKEND_PROBE_PASS persistent-owner view-rebuilds viewport detached-core exporter native-turns pedestrian-turns units typed-guidance unicode terminal-states");
    return 0;
}
