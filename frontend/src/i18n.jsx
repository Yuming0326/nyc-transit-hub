import React, { createContext, useContext, useMemo, useState } from 'react';

const dictionaries = {
  en: {
    appName: 'NYC Transit Hub', tagline: 'Plan with live and scheduled transit information.',
    dashboard: 'Dashboard', explore: 'Explore & map', planner: 'Journey planner', services: 'Service info', notifications: 'Notifications',
    language: 'Language', english: 'English', chinese: '简体中文', signIn: 'Sign in with Google', signOut: 'Sign out',
    liveMode: 'Live mode', demoMode: 'Demo mode', modeUnavailable: 'Backend mode unavailable', checkingBackend: 'Checking backend…',
    retry: 'Retry', loading: 'Loading…', unavailable: 'Unavailable', unknown: 'Unknown', updated: 'Updated', source: 'Source',
    originalMta: 'MTA notices are shown in their original language.',
    exploreTransit: 'Explore transit', subway: 'Subway', bus: 'Bus', searchRoutes: 'Search routes', searchRoutesHint: 'Route name or label', noRoutes: 'No routes match your search.', stopsStations: 'Stops & stations', noStops: 'No stations or stops are listed for this route.', interactiveMap: 'Interactive map', refreshMap: 'Refresh map',
    planJourney: 'Plan a journey', origin: 'Origin', destination: 'Destination', departure: 'Departure date and time', findJourneys: 'Find journeys', journeyOptions: 'Journey options',
    serviceStatus: 'Service status', refresh: 'Refresh', equipment: 'Elevators & escalators', coverage: 'Coverage',
    subscriptions: 'Subscriptions', selectedStation: 'Selected station', enableAlerts: 'Enable station alerts', disableAlerts: 'Disable station alerts', signInNotifications: 'Sign in to manage subscriptions and view private notifications.', noNotifications: 'No notifications yet.',
  },
  zh: {
    appName: '纽约交通中心', tagline: '结合实时与计划时刻信息规划出行。',
    dashboard: '实时面板', explore: '线路与地图', planner: '行程规划', services: '服务信息', notifications: '通知',
    language: '语言', english: 'English', chinese: '简体中文', signIn: '使用 Google 登录', signOut: '退出登录',
    liveMode: '实时模式', demoMode: '演示模式', modeUnavailable: '无法确认后端模式', checkingBackend: '正在检查后端…',
    retry: '重试', loading: '加载中…', unavailable: '不可用', unknown: '未知', updated: '更新时间', source: '来源',
    originalMta: 'MTA 公告保留其原始语言，不自动翻译。',
    exploreTransit: '探索公共交通', subway: '地铁', bus: '公交', searchRoutes: '搜索线路', searchRoutesHint: '线路名称或编号', noRoutes: '没有符合条件的线路。', stopsStations: '站点与车站', noStops: '这条线路暂无站点信息。', interactiveMap: '交互式地图', refreshMap: '刷新地图',
    planJourney: '规划行程', origin: '起点', destination: '终点', departure: '出发日期和时间', findJourneys: '查找行程', journeyOptions: '行程方案',
    serviceStatus: '服务状态', refresh: '刷新', equipment: '电梯与扶梯', coverage: '数据覆盖情况',
    subscriptions: '订阅', selectedStation: '当前车站', enableAlerts: '启用车站提醒', disableAlerts: '停用车站提醒', signInNotifications: '登录后可管理订阅并查看私人通知。', noNotifications: '暂无通知。',
  },
};

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(() => localStorage.getItem('transit-language') || 'en');
  function setLanguage(value) {
    const next = value === 'zh' ? 'zh' : 'en';
    localStorage.setItem('transit-language', next);
    document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en';
    setLanguageState(next);
  }
  const value = useMemo(() => ({ language, setLanguage, t: key => dictionaries[language][key] || dictionaries.en[key] || key }), [language]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
