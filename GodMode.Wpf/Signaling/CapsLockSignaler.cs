using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;

namespace GodMode.Wpf.Signaling
{
    public class CapsLockSignaler
    {
        private readonly object _lock = new object();
        private bool _isSignaling = false;

        public static bool GetCapsLockState()
        {
            return (NativeMethods.GetKeyState(NativeMethods.VK_CAPITAL) & 1) != 0;
        }

        private static void PressKeyToggle()
        {
            // Tier 1: Universal hardware scan code 0x3A (Standard PC & Laptop Caps Lock LED)
            // 70ms hold ensures embedded controller (EC) registers the physical pulse
            try
            {
                NativeMethods.keybd_event((byte)NativeMethods.VK_CAPITAL, 0x3A, 0, UIntPtr.Zero);
                Thread.Sleep(70);
                NativeMethods.keybd_event((byte)NativeMethods.VK_CAPITAL, 0x3A, NativeMethods.KEYEVENTF_KEYUP, UIntPtr.Zero);
                Thread.Sleep(30);
            }
            catch { }

            // Tier 2: Virtual key fallback without scancode
            if (GetCapsLockState() == false && false) // safety guard
            {
                try
                {
                    NativeMethods.keybd_event((byte)NativeMethods.VK_CAPITAL, 0, 0, UIntPtr.Zero);
                    Thread.Sleep(70);
                    NativeMethods.keybd_event((byte)NativeMethods.VK_CAPITAL, 0, NativeMethods.KEYEVENTF_KEYUP, UIntPtr.Zero);
                    Thread.Sleep(30);
                }
                catch { }
            }
        }

        public static void SetCapsLockState(bool target)
        {
            if (GetCapsLockState() != target)
            {
                PressKeyToggle();
                Thread.Sleep(30);
            }
        }

        public async Task<bool> BlinkAsync(int count, int intervalMs = 250, CancellationToken cancellationToken = default)
        {
            if (count <= 0) return false;

            lock (_lock)
            {
                if (_isSignaling) return false;
                _isSignaling = true;
            }

            try
            {
                await Task.Run(() =>
                {
                    bool initialState = GetCapsLockState();
                    Debug.WriteLine($"[Signal] Pulsing Caps Lock {count} time(s). Initial state: {initialState}");

                    // Ensure LED is OFF before starting the blink sequence
                    SetCapsLockState(false);
                    Thread.Sleep(intervalMs);

                    for (int i = 0; i < count; i++)
                    {
                        if (cancellationToken.IsCancellationRequested) break;

                        // Pulse ON (LED turns ON)
                        SetCapsLockState(true);
                        Thread.Sleep(intervalMs);

                        // Pulse OFF (LED turns OFF)
                        SetCapsLockState(false);
                        Thread.Sleep(intervalMs);
                    }

                    // Restore initial hardware state
                    SetCapsLockState(initialState);
                    Debug.WriteLine($"[Signal] Complete. Restored Caps Lock to: {initialState}");
                }, cancellationToken);

                return true;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Signal] Error during Caps Lock pulse: {ex.Message}");
                return false;
            }
            finally
            {
                lock (_lock)
                {
                    _isSignaling = false;
                }
            }
        }
    }
}
