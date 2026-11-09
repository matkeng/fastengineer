// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import './style.css';

createApp(App).use(createPinia()).mount('#app');
