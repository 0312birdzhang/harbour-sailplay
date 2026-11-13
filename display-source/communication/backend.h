#ifndef SAILPLAY_COMMUNICATION_BACKEND_H
#define SAILPLAY_COMMUNICATION_BACKEND_H

#include "sailplayprovider.h"
#include <QAbstractItemModel>
#include <QTimer>

class CommunicationBackend : public QObject
{
    Q_OBJECT
public:
    CommunicationBackend(const QString &kind, QObject *models, QObject *parent = nullptr);
    bool start();

private slots:
    void invalidate();
    void conversationReady(bool successful);
    void messageFinished(const QString &token, const QString &error);

private:
    QVariant callModels(const char *method, const QVariantList &arguments = {}) const;
    QVariantList threads() const;
    QVariantMap rootPage() const;
    void refresh();
    void browse(qulonglong invocation, const QVariantMap &parameters, bool search);
    void finishConversation();
    void mutate(qulonglong invocation, const QString &action, const QVariantMap &parameters);
    void systemCall(qulonglong invocation, const QString &service, const QString &path,
                    const QString &interface, const QString &method, const QVariantList &arguments);
    QString m_kind;
    QObject *m_models;
    SailplayProvider *m_provider = nullptr;
    QVariantMap m_state;
    qulonglong m_contentVersion = 1;
    QTimer m_poll;
    QTimer m_idle;
    QTimer m_contentTimer;
    QTimer m_queryTimer;
    QAbstractItemModel *m_conversation = nullptr;
    bool m_conversationLoaded = false;
    int m_group = -1;
    qulonglong m_query = 0;
    qulonglong m_queryVersion = 0;
    QVariantMap m_parameters;
    QString m_threadTitle;
    bool m_mutationPending = false;
    qulonglong m_messageInvocation = 0;
};

#endif
