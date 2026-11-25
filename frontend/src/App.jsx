import React from 'react';
import HomePage from './pages/HomePage';
import { I18nProvider } from './i18n';
export default function App() { return <I18nProvider><HomePage /></I18nProvider>; }
