//! Tauri shell: starts the Python engine sidecar on a free localhost port,
//! tells the front end where it is, and stops it on exit.

use std::net::TcpListener;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct Engine {
    url: Result<String, String>,
    child: Mutex<Option<CommandChild>>,
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init()) // Save As dialog for exports
        .setup(|app| {
            // A failed engine start is reported in the UI rather than crashing the shell.
            let engine = match start_engine(app.handle()) {
                Ok((url, child)) => Engine { url: Ok(url), child: Mutex::new(Some(child)) },
                Err(e) => {
                    eprintln!("{e}");
                    Engine { url: Err(e), child: Mutex::new(None) }
                }
            };
            app.manage(engine);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_url])
        .build(tauri::generate_context!())
        .expect("error while building Drawing Workbench")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Engine>().child.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
