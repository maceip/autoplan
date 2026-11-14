'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nucleusDesktop', {
  getRuntimeInfo: () => ipcRenderer.invoke('nucleus:get-runtime-info'),
  getServicesStatus: () => ipcRenderer.invoke('nucleus:get-services-status'),
  ensureLocalServices: () => ipcRenderer.invoke('nucleus:ensure-local-services'),
  openExternal: (url) => ipcRenderer.invoke('nucleus:open-external', url),
});
