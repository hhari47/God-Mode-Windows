using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Interop;

namespace GodMode.Wpf.Hotkeys
{
    public class HotkeyManager : IDisposable
    {
        private const int HOTKEY_ID_SOLVE = 1;
        private const int HOTKEY_ID_OCR = 2;

        private HwndSource? _hwndSource;
        private IntPtr _hookId = IntPtr.Zero;
        private NativeMethods.LowLevelKeyboardProc? _hookProc;
        private bool _disposed = false;

        private DateTime _lastSolveTime = DateTime.MinValue;
        private DateTime _lastOcrTime = DateTime.MinValue;
        private bool _xKeyDown = false;
        private bool _oKeyDown = false;

        public event Action? SolveSelectedTriggered;
        public event Action? ScreenOcrTriggered;

        public bool IsRegisteredSolve { get; private set; }
        public bool IsRegisteredOcr { get; private set; }

        public HotkeyManager()
        {
            InitializeMessageOnlyWindow();
            InstallLowLevelHook();
        }

        private void InitializeMessageOnlyWindow()
        {
            try
            {
                // Create dedicated Win32 message-only window via HWND_MESSAGE
                var parameters = new HwndSourceParameters("GodMode_MessageOnly_Window")
                {
                    ParentWindow = NativeMethods.HWND_MESSAGE,
                    WindowStyle = 0
                };

                _hwndSource = new HwndSource(parameters);
                _hwndSource.AddHook(WndProc);

                IntPtr hwnd = _hwndSource.Handle;

                // Register Ctrl + Alt + X (Solve Selected)
                IsRegisteredSolve = NativeMethods.RegisterHotKey(
                    hwnd,
                    HOTKEY_ID_SOLVE,
                    NativeMethods.MOD_CONTROL | NativeMethods.MOD_ALT | NativeMethods.MOD_NOREPEAT,
                    NativeMethods.VK_X
                );

                // Register Ctrl + Alt + O (Screen OCR)
                IsRegisteredOcr = NativeMethods.RegisterHotKey(
                    hwnd,
                    HOTKEY_ID_OCR,
                    NativeMethods.MOD_CONTROL | NativeMethods.MOD_ALT | NativeMethods.MOD_NOREPEAT,
                    NativeMethods.VK_O
                );

                Debug.WriteLine($"[Hotkeys] RegisterHotKey HWND_MESSAGE: Solve={IsRegisteredSolve}, OCR={IsRegisteredOcr}");
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Hotkeys] Error creating message-only window: {ex.Message}");
            }
        }

        private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            if (msg == NativeMethods.WM_HOTKEY)
            {
                int id = wParam.ToInt32();
                if (id == HOTKEY_ID_SOLVE)
                {
                    TriggerSolveSelected();
                    handled = true;
                }
                else if (id == HOTKEY_ID_OCR)
                {
                    TriggerScreenOcr();
                    handled = true;
                }
            }
            return IntPtr.Zero;
        }

        private void InstallLowLevelHook()
        {
            try
            {
                _hookProc = HookCallback;
                using var curProcess = Process.GetCurrentProcess();
                using var curModule = curProcess.MainModule;
                IntPtr modHandle = curModule?.ModuleName != null
                    ? NativeMethods.GetModuleHandle(curModule.ModuleName)
                    : IntPtr.Zero;

                _hookId = NativeMethods.SetWindowsHookEx(
                    NativeMethods.WH_KEYBOARD_LL,
                    _hookProc,
                    modHandle,
                    0
                );
                Debug.WriteLine($"[Hotkeys] Low-level keyboard hook installed: {(_hookId != IntPtr.Zero)}");
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Hotkeys] Error installing low-level hook: {ex.Message}");
            }
        }

        private IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
        {
            if (nCode >= 0)
            {
                int msg = wParam.ToInt32();
                int vkCode = Marshal.ReadInt32(lParam);

                bool isCtrlDown = (NativeMethods.GetAsyncKeyState(NativeMethods.VK_CONTROL) & 0x8000) != 0;
                bool isAltDown = (NativeMethods.GetAsyncKeyState(NativeMethods.VK_MENU) & 0x8000) != 0;

                if (vkCode == NativeMethods.VK_X)
                {
                    if (msg == NativeMethods.WM_KEYDOWN || msg == NativeMethods.WM_SYSKEYDOWN)
                    {
                        if (isCtrlDown && isAltDown && !_xKeyDown)
                        {
                            _xKeyDown = true;
                            TriggerSolveSelected();
                        }
                    }
                    else if (msg == NativeMethods.WM_KEYUP || msg == NativeMethods.WM_SYSKEYUP)
                    {
                        _xKeyDown = false;
                    }
                }
                else if (vkCode == NativeMethods.VK_O)
                {
                    if (msg == NativeMethods.WM_KEYDOWN || msg == NativeMethods.WM_SYSKEYDOWN)
                    {
                        if (isCtrlDown && isAltDown && !_oKeyDown)
                        {
                            _oKeyDown = true;
                            TriggerScreenOcr();
                        }
                    }
                    else if (msg == NativeMethods.WM_KEYUP || msg == NativeMethods.WM_SYSKEYUP)
                    {
                        _oKeyDown = false;
                    }
                }
            }
            return NativeMethods.CallNextHookEx(_hookId, nCode, wParam, lParam);
        }

        private void TriggerSolveSelected()
        {
            var now = DateTime.UtcNow;
            if ((now - _lastSolveTime).TotalMilliseconds < 400)
                return;
            _lastSolveTime = now;
            SolveSelectedTriggered?.Invoke();
        }

        private void TriggerScreenOcr()
        {
            var now = DateTime.UtcNow;
            if ((now - _lastOcrTime).TotalMilliseconds < 400)
                return;
            _lastOcrTime = now;
            ScreenOcrTriggered?.Invoke();
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            if (_hwndSource != null)
            {
                IntPtr hwnd = _hwndSource.Handle;
                NativeMethods.UnregisterHotKey(hwnd, HOTKEY_ID_SOLVE);
                NativeMethods.UnregisterHotKey(hwnd, HOTKEY_ID_OCR);
                _hwndSource.RemoveHook(WndProc);
                _hwndSource.Dispose();
                _hwndSource = null;
            }

            if (_hookId != IntPtr.Zero)
            {
                NativeMethods.UnhookWindowsHookEx(_hookId);
                _hookId = IntPtr.Zero;
            }
        }
    }
}
