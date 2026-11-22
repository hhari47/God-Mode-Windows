using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows;
using System.Windows.Forms;
using GodMode.Wpf.Configuration;
using GodMode.Wpf.Hotkeys;

namespace GodMode.Wpf
{
    public partial class App : System.Windows.Application
    {
        private const string MutexName = @"Global\GodModeWindows_SingleInstance_Mutex_v2";
        private Mutex? _instanceMutex;
        private bool _hasMutexOwnership = false;

        private NotifyIcon? _notifyIcon;
        private ContextMenuStrip? _trayMenu;
        private HotkeyManager? _hotkeyManager;
        private MainWindow? _mainWindow;
        private AppConfig? _config;
        private bool _isDisposed = false;

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);

            // 1. Single Instance Named Mutex Check
            try
            {
                _instanceMutex = new Mutex(true, MutexName, out bool isNewInstance);
                _hasMutexOwnership = isNewInstance;
                if (!isNewInstance)
                {
                    // Signal the already-running instance to show its window immediately
                    NativeMethods.PostMessage(NativeMethods.HWND_BROADCAST, HotkeyManager.WM_SHOW_GODMODE, IntPtr.Zero, IntPtr.Zero);
                    Shutdown();
                    return;
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Mutex] Error: {ex.Message}");
            }

            // 2. Load Configuration
            _config = AppConfig.Load();

            // 3. Initialize Overlay Window
            _mainWindow = new MainWindow(_config);

            // 4. Initialize Hotkey Manager (HWND_MESSAGE + Low Level Hook fallback)
            _hotkeyManager = new HotkeyManager();
            _hotkeyManager.SolveSelectedTriggered += OnSolveSelectedTriggered;
            _hotkeyManager.ScreenOcrTriggered += OnScreenOcrTriggered;
            _hotkeyManager.ToggleUiTriggered += ToggleOverlayWindow;

            // 5. Initialize System Tray NotifyIcon
            InitializeTrayIcon();

            // 6. Reveal window on launch unless start minimized is explicitly configured
            if (!_config.StartMinimized || e.Args.Contains("--show"))
            {
                _mainWindow.Show();
                _mainWindow.Activate();
            }
        }

        private void InitializeTrayIcon()
        {
            try
            {
                _trayMenu = new ContextMenuStrip();

                // Header
                var headerItem = new ToolStripMenuItem("⚡ GodMode v2.0 (Active)")
                {
                    Enabled = false,
                    Font = new Font(System.Drawing.SystemFonts.DefaultFont, System.Drawing.FontStyle.Bold)
                };
                _trayMenu.Items.Add(headerItem);
                _trayMenu.Items.Add(new ToolStripSeparator());

                // Show / Hide Overlay
                var toggleItem = new ToolStripMenuItem("Show / Hide Overlay", null, (s, ev) => ToggleOverlayWindow());
                _trayMenu.Items.Add(toggleItem);

                // Quick Action: Solve Selected
                var solveItem = new ToolStripMenuItem("Solve Selected (Ctrl+Alt+X)", null, async (s, ev) =>
                {
                    if (_mainWindow != null)
                        await _mainWindow.TriggerSolveSelectedFlowAsync();
                });
                _trayMenu.Items.Add(solveItem);

                // Quick Action: Screen OCR
                var ocrItem = new ToolStripMenuItem("Screen OCR (Ctrl+Alt+O)", null, async (s, ev) =>
                {
                    if (_mainWindow != null)
                        await _mainWindow.TriggerScreenOcrFlowAsync();
                });
                _trayMenu.Items.Add(ocrItem);

                _trayMenu.Items.Add(new ToolStripSeparator());

                // Settings
                var settingsItem = new ToolStripMenuItem("Settings...", null, (s, ev) =>
                {
                    if (_mainWindow != null)
                    {
                        _mainWindow.ShowSettings();
                    }
                });
                _trayMenu.Items.Add(settingsItem);

                _trayMenu.Items.Add(new ToolStripSeparator());

                // Quit
                var quitItem = new ToolStripMenuItem("Quit GodMode", null, (s, ev) => ShutdownApp());
                _trayMenu.Items.Add(quitItem);

                // Icon Resolution
                Icon trayIcon = SystemIcons.Shield;
                try
                {
                    string iconPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "icon.ico");
                    if (!File.Exists(iconPath))
                    {
                        iconPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", "..", "..", "assets", "icon.ico");
                    }
                    if (File.Exists(iconPath))
                    {
                        trayIcon = new Icon(iconPath);
                    }
                    else
                    {
                        var exePath = Environment.ProcessPath ?? Process.GetCurrentProcess().MainModule?.FileName;
                        if (!string.IsNullOrEmpty(exePath) && File.Exists(exePath))
                        {
                            var extracted = Icon.ExtractAssociatedIcon(exePath);
                            if (extracted != null) trayIcon = extracted;
                        }
                    }
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[Tray] Icon load error: {ex.Message}");
                }

                _notifyIcon = new NotifyIcon
                {
                    Icon = trayIcon,
                    Text = "GodMode — AI Question Solver\nCtrl+Alt+X: Solve Selected\nCtrl+Alt+O: Silent OCR",
                    Visible = true,
                    ContextMenuStrip = _trayMenu
                };

                _notifyIcon.DoubleClick += (s, ev) => ToggleOverlayWindow();

                // Subtle system notification
                _notifyIcon.ShowBalloonTip(
                    2500,
                    "GodMode Active",
                    "Running covertly in system tray.\nCtrl+Alt+X: Solve Selected | Ctrl+Alt+O: OCR",
                    ToolTipIcon.Info
                );
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Tray] Initialization failed: {ex.Message}");
            }
        }

        private void ToggleOverlayWindow()
        {
            if (_mainWindow == null) return;

            Dispatcher.Invoke(() =>
            {
                if (_mainWindow.IsVisible)
                {
                    _mainWindow.Hide();
                }
                else
                {
                    _mainWindow.Show();
                    _mainWindow.Activate();
                    _mainWindow.WindowState = WindowState.Normal;
                }
            });
        }

        private async void OnSolveSelectedTriggered()
        {
            if (_mainWindow == null) return;
            // Solve silently without forcing window popup (overlay stays covert)
            await _mainWindow.TriggerSolveSelectedFlowAsync();
        }

        private async void OnScreenOcrTriggered()
        {
            if (_mainWindow == null) return;
            // Solve silently without forcing window popup (overlay stays covert)
            await _mainWindow.TriggerScreenOcrFlowAsync();
        }

        public void ShutdownApp()
        {
            if (_isDisposed) return;
            _isDisposed = true;

            try
            {
                if (_notifyIcon != null)
                {
                    _notifyIcon.Visible = false;
                    _notifyIcon.Dispose();
                    _notifyIcon = null;
                }

                if (_trayMenu != null)
                {
                    _trayMenu.Dispose();
                    _trayMenu = null;
                }

                if (_hotkeyManager != null)
                {
                    _hotkeyManager.Dispose();
                    _hotkeyManager = null;
                }

                if (_mainWindow != null)
                {
                    _mainWindow.ForceClose();
                    _mainWindow = null;
                }

                if (_instanceMutex != null)
                {
                    if (_hasMutexOwnership)
                    {
                        try { _instanceMutex.ReleaseMutex(); } catch { }
                    }
                    _instanceMutex.Dispose();
                    _instanceMutex = null;
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Shutdown] Cleanup exception: {ex.Message}");
            }
            finally
            {
                System.Windows.Application.Current.Shutdown();
            }
        }

        protected override void OnExit(ExitEventArgs e)
        {
            ShutdownApp();
            base.OnExit(e);
        }
    }
}
