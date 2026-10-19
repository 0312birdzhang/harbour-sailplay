#include <QGuiApplication>
#include <QQuickView>
#include <QQuickItem>
#include <sailfishapp.h>
#include <QScreen>
#include <QTimer>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <unistd.h>
#include <cstdio>
int main(int argc,char**argv){
 QGuiApplication app(argc,argv);
 const QString record=QString("/run/user/100000/sailplay-app-%1").arg(getpid());
 QFile stat(QString("/proc/%1/stat").arg(getpid()));stat.open(QIODevice::ReadOnly);QByteArray data=stat.readAll();
 QFile identity(record);identity.open(QIODevice::WriteOnly);identity.write(qgetenv("CARLIFE_APP_KEY")+'\n'+data.mid(data.lastIndexOf(')')+2).simplified().split(' ')[19]+'\n');identity.close();
 QQuickView &view=*SailfishApp::createView();view.setTitle("Sailplay geometry probe");view.setResizeMode(QQuickView::SizeRootObjectToView);view.setSource(QUrl::fromLocalFile("/tmp/sailplay-viewport-probe.qml"));view.show();
 QTimer timer;QObject::connect(&timer,&QTimer::timeout,[&](){
  const QSize screen=view.screen()->geometry().size();
  QJsonObject state{{"width",view.width()},{"height",view.height()},{"screenWidth",screen.width()},{"screenHeight",screen.height()}};
  state.insert("silicaWidth",view.rootObject()->property("silicaWidth").toInt());state.insert("silicaHeight",view.rootObject()->property("silicaHeight").toInt());
  state.insert("pageWidth",view.rootObject()->property("pageWidth").toInt());state.insert("pageHeight",view.rootObject()->property("pageHeight").toInt());
  QFile output("/tmp/sailplay-viewport-observed.json");output.open(QIODevice::WriteOnly);output.write(QJsonDocument(state).toJson());
 });timer.start(100);QTimer::singleShot(30000,&app,&QCoreApplication::quit);
 const int result=app.exec();QFile::remove(record);return result;
}
