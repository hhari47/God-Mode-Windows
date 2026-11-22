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
            // Key down
            NativeMethods.keybd_event(
                NativeMethods.VK_CAPITAL,
                NativeMethods.SCANCODE_CAPSLOCK,
                NativeMethods.KEYEVENTF_EXTENDEDKEY,
                UIntPtr.Zero
            );

            // Hold 70ms (Microsoft KB177674 standard)
            Thread.Sleep(70);

            // Key up
            NativeMethods.keybd_event(
                NativeMethods.VK_CAPITAL,
                NativeMethods.SCANCODE_CAPSLOCK,
                NativeMethods.KEYEVENTF_EXTENDEDKEY | NativeMethods.KEYEVENTF_KEYUP,
                UIntPtr.Zero
            );
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
                    if (GetCapsLockState())
                    {
                        SetCapsLockState(false);
                        Thread.Sleep(intervalMs);
                    }

                    for (int i = 0; i < count; i++)
                    {
                        if (cancellationToken.IsCancellationRequested) break;

                        // Pulse ON (single distinct blink)
                        SetCapsLockState(true);
                        Thread.Sleep(intervalMs);

                        // Pulse OFF
                        SetCapsLockState(false);
                        Thread.Sleep(intervalMs);
                    }

                    // Restore initial hardware state
                    if (GetCapsLockState() != initialState)
                    {
                        SetCapsLockState(initialState);
                    }
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

