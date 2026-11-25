import React from 'react';
import { useI18n } from '../i18n';

export default function ResourceState({ loading, error, data, onRetry, children, empty, emptyMessage = 'No information is available.' }) {
  const { t } = useI18n();
  if (loading && !data) return <p role="status">{t('loading')}</p>;
  if (error && !data) return <div className="state-message"><p className="error" role="alert">{error}</p>{onRetry && <button type="button" onClick={onRetry}>{t('retry')}</button>}</div>;
  return <>{error && <p className="error" role="alert">{error} Showing the last successful response.</p>}{empty ? <p>{emptyMessage}</p> : children}</>;
}
