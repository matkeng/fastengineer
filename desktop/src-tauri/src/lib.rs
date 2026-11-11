// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
//! Tauri shell: starts the Python engine sidecar on a free localhost port,
//! tells the front end where it is, and stops it on exit.
//!
//! Multi-user: when a shared server is configured (see `server_url`) no sidecar is
//! started; the front end talks to the engine on the server instead, and every
//! request carries the Windows login from `client_identity`.

use std::net::TcpListener;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct Engine {
    url: Result<String, String>,
    child: Mutex<Option<CommandChild>>,
    /// The engine is a shared server on another machine, not our own sidecar.
    remote: bool,
}

/// Who is using this PC. Sent with every request so the engine can record who
/// changed what. It is the Windows session's own login, not something typed in.
#[derive(serde::Serialize)]
struct ClientIdentity {
    user: String,
    machine: String,
    remote: bool,
}

#[tauri::command]
fn client_identity(engine: State<'_, Engine>) -> ClientIdentity {
    let var = |name: &str| std::env::var(name).unwrap_or_default();
    // Windows: USERDOMAIN\USERNAME on COMPUTERNAME. Elsewhere (development): USER on HOSTNAME.
    let name = [var("USERNAME"), var("USER")].into_iter().find(|v| !v.is_empty()).unwrap_or_default();
    let domain = var("USERDOMAIN");
    let user = if domain.is_empty() || name.is_empty() { name } else { format!("{domain}\\{name}") };
    let machine = [var("COMPUTERNAME"), var("HOSTNAME")].into_iter().find(|v| !v.is_empty()).unwrap_or_default();
    ClientIdentity { user, machine, remote: engine.remote }
}

/// Writes an export to the path the user picked in the Save As dialog. Used with a
/// shared server, which cannot write to this PC's disks itself.
#[tauri::command]
fn save_bytes(path: String, bytes: Vec<u8>) -> Result<(), String> {
    std::fs::write(&path, bytes).map_err(|e| format!("can't save {path}: {e}"))
}

/// The shared server to use instead of a local engine, if IT configured one:
/// the `WORKBENCH_SERVER_URL` environment variable, or `server_url` in
/// `%PROGRAMDATA%\DrawingWorkbench\client.json` (one file for every user of the PC),
/// e.g. `{"server_url": "http://SERVERNAME:8765"}`.
fn server_url() -> Option<String> {
    let from_file = || {
        let dir = std::env::var("PROGRAMDATA").ok()?;
        let path = std::path::Path::new(&dir).join("DrawingWorkbench").join("client.json");
        let text = std::fs::read_to_string(path).ok()?;
        let config: serde_json::Value = serde_json::from_str(text.trim_start_matches('\u{feff}')).ok()?;
        Some(config.get("server_url")?.as_str()?.to_string())
    };
    let url = std::env::var("WORKBENCH_SERVER_URL").ok().or_else(from_file)?;
    let url = url.trim().trim_end_matches('/').to_string();
    (url.starts_with("http://") || url.starts_with("https://")).then_some(url)
}

/// Returns the engine base URL, or the reason the engine failed to start.
#[tauri::command]
fn engine_url(engine: State<'_, Engine>) -> Result<String, String> {
    engine.url.clone()
}

fn free_port() -> std::io::Result<u16> {
    // Bind to port 0 so the OS picks a free port, then release it for the engine.
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

fn start_engine(app: &tauri::AppHandle) -> Result<(String, CommandChild), String> {
    let port = free_port().map_err(|e| format!("no free port: {e}"))?;
    // Saved imports live in the per-user app data folder, e.g.
    // %APPDATA%\com.drawingworkbench.poc\workbench.db on Windows.
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("no app data folder: {e}"))?;
    std::fs::create_dir_all(&data_dir).map_err(|e| format!("can't create {}: {e}", data_dir.display()))?;
    let (mut rx, child) = app
        .shell()
        .sidecar("workbench-engine")
        .map_err(|e| format!("sidecar not found: {e}"))?
        .args([
            "--port".to_string(),
            port.to_string(),
            "--parent-pid".to_string(),
            std::process::id().to_string(),
            "--data-dir".to_string(),
            data_dir.to_string_lossy().into_owned(),
        ])
        .spawn()
        .map_err(|e| format!("failed to start engine: {e}"))?;

    // Forward engine output to the shell's stdout/stderr (visible in `tauri dev`).
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => print!("[engine] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Stderr(line) => eprint!("[engine] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Terminated(p) => eprintln!("[engine] exited: {:?}", p.code),
                _ => {}
            }
        }
    });

    Ok((format!("http://127.0.0.1:{port}"), child))
}

/// Ends the engine when the app closes. The engine is a onefile program: the process we
/// started only unpacks and starts the real engine as its child, so on Windows the whole
/// process tree is ended (`taskkill /T`), not just the process we hold.
fn stop_engine(child: CommandChild) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &child.pid().to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }
    let _ = child.kill();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init()) // Save As dialog for exports
        .setup(|app| {
            // A failed engine start is reported in the UI rather than crashing the shell.
            let engine = if let Some(url) = server_url() {
                println!("[shell] using the shared engine at {url}");
                Engine { url: Ok(url), child: Mutex::new(None), remote: true }
            } else {
                match start_engine(app.handle()) {
                    Ok((url, child)) => Engine { url: Ok(url), child: Mutex::new(Some(child)), remote: false },
                    Err(e) => {
                        eprintln!("{e}");
                        Engine { url: Err(e), child: Mutex::new(None), remote: false }
                    }
                }
            };
            app.manage(engine);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_url, client_identity, save_bytes])
        .build(tauri::generate_context!())
        .expect("error while building Drawing Workbench")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Engine>().child.lock().unwrap().take() {
                    stop_engine(child);
                }
            }
        });
}
