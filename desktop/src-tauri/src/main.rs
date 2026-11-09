// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    drawing_workbench_lib::run()
}
