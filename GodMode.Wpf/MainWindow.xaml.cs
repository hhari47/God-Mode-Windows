using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;
using GodMode.Wpf.AI;
using GodMode.Wpf.Configuration;
using GodMode.Wpf.OCR;
using GodMode.Wpf.Signaling;
using GodMode.Wpf.TextProcessing;

namespace GodMode.Wpf
{
    public partial class MainWindow : Window
    {
        private readonly AppConfig _config;
        private readonly AiSolver _aiSolver;
        private readonly CapsLockSignaler _signaler;
        private bool _isProcessing = false;

        public MainWindow(AppConfig config)
        {
            InitializeComponent();
            _config = config;
            _aiSolver = new AiSolver(_config);
            _signaler = new CapsLockSignaler();

            // Populate settings view with loaded config
            GeminiKeyBox.Text = _config.GeminiApiKey;
            GeminiModelBox.Text = _config.GeminiModel;
            BlinkDurationBox.Text = _config.BlinkDurationMs.ToString();
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);

            // Win32 Overlay Setup: Apply WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, and WDA_EXCLUDEFROMCAPTURE
            IntPtr hwnd = new WindowInteropHelper(this).Handle;
            if (hwnd != IntPtr.Zero)
            {
                int exStyle = NativeMethods.GetWindowLong(hwnd, NativeMethods.GWL_EXSTYLE);
                NativeMethods.SetWindowLong(
                    hwnd,
                    NativeMethods.GWL_EXSTYLE,
                    exStyle | NativeMethods.WS_EX_TOOLWINDOW | NativeMethods.WS_EX_NOACTIVATE
                );

                // Ensure covert invisibility to proctoring / screen share recording
                NativeMethods.SetWindowDisplayAffinity(hwnd, NativeMethods.WDA_EXCLUDEFROMCAPTURE);
            }
        }

        private bool _allowClose = false;

        public void ForceClose()
        {
            _allowClose = true;
            this.Close();
        }

        public void ShowSettings()
        {
            this.Show();
            this.Activate();
            WorkspaceView.Visibility = Visibility.Collapsed;
            HistoryView.Visibility = Visibility.Collapsed;
            SettingsView.Visibility = Visibility.Visible;
        }

        protected override void OnClosing(CancelEventArgs e)
        {
            // Intercept window close: Never terminate the process, always Hide() to system tray
            if (!_allowClose)
            {
                e.Cancel = true;
                this.Hide();
            }
        }

        private void TitleBar_MouseDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ChangedButton == MouseButton.Left)
            {
                this.DragMove();
            }
        }

        private void MinimizeBtn_Click(object sender, RoutedEventArgs e)
        {
            this.Hide();
        }

        private void CloseBtn_Click(object sender, RoutedEventArgs e)
        {
            this.Hide();
        }

        // ── Navigation ──
        private void NavWorkspace_Click(object sender, RoutedEventArgs e)
        {
            WorkspaceView.Visibility = Visibility.Visible;
            HistoryView.Visibility = Visibility.Collapsed;
            SettingsView.Visibility = Visibility.Collapsed;
        }

        private void NavHistory_Click(object sender, RoutedEventArgs e)
        {
            WorkspaceView.Visibility = Visibility.Collapsed;
            HistoryView.Visibility = Visibility.Visible;
            SettingsView.Visibility = Visibility.Collapsed;
        }

        private void NavSettings_Click(object sender, RoutedEventArgs e)
        {
            WorkspaceView.Visibility = Visibility.Collapsed;
            HistoryView.Visibility = Visibility.Collapsed;
            SettingsView.Visibility = Visibility.Visible;
        }

        // ── Actions ──
        private async void ProcessBtn_Click(object sender, RoutedEventArgs e)
        {
            string input = QuestionInputBox.Text.Trim();
            if (string.IsNullOrEmpty(input))
            {
                System.Windows.MessageBox.Show("Please enter or capture a question first.", "GodMode", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            await SolveTextAsync(input);
        }

        private void ClearBtn_Click(object sender, RoutedEventArgs e)
        {
            QuestionInputBox.Clear();
            ParsedStemBlock.Text = "Question stem will appear here...";
            ParsedOptionsBlock.Text = "Options will appear here...";
            KeyResultText.Text = "Awaiting input...";
            AiReasoningBlock.Text = "Reasoning details will appear here after evaluation...";
        }

        private async void PasteAndSolveBtn_Click(object sender, RoutedEventArgs e)
        {
            if (System.Windows.Clipboard.ContainsText())
            {
                string text = System.Windows.Clipboard.GetText().Trim();
                QuestionInputBox.Text = text;
                await SolveTextAsync(text);
            }
        }

        private async void SolveSelectedBtn_Click(object sender, RoutedEventArgs e)
        {
            await TriggerSolveSelectedFlowAsync();
        }

        private async void ScreenOcrBtn_Click(object sender, RoutedEventArgs e)
        {
            await TriggerScreenOcrFlowAsync();
        }

        public async Task TriggerSolveSelectedFlowAsync()
        {
            if (_isProcessing) return;

            // Covert clipboard grab
            string? captured = await CaptureSelectedTextAsync();
            if (!string.IsNullOrWhiteSpace(captured))
            {
                Dispatcher.Invoke(() =>
                {
                    QuestionInputBox.Text = captured;
                });
                await SolveTextAsync(captured);
            }
        }

        public async Task TriggerScreenOcrFlowAsync()
        {
            if (_isProcessing) return;

            Dispatcher.Invoke(() =>
            {
                StatusBarText.Text = "📷 Running Screen OCR...";
            });

            string? ocrText = await ScreenOcrEngine.CaptureScreenAndOcrAsync();
            if (!string.IsNullOrWhiteSpace(ocrText))
            {
                Dispatcher.Invoke(() =>
                {
                    QuestionInputBox.Text = ocrText;
                });
                await SolveTextAsync(ocrText);
            }
            else
            {
                Dispatcher.Invoke(() =>
                {
                    StatusBarText.Text = "⚠️ Screen OCR returned no text.";
                });
            }
        }

        private async Task<string?> CaptureSelectedTextAsync()
        {
            try
            {
                // Save original clipboard
                string? prevClipboard = null;
                try { if (System.Windows.Clipboard.ContainsText()) prevClipboard = System.Windows.Clipboard.GetText(); } catch { }

                // Simulate Ctrl+C
                NativeMethods.keybd_event((byte)NativeMethods.VK_CONTROL, 0, 0, UIntPtr.Zero);
                NativeMethods.keybd_event((byte)NativeMethods.VK_C, 0, 0, UIntPtr.Zero);
                await Task.Delay(40);
                NativeMethods.keybd_event((byte)NativeMethods.VK_C, 0, NativeMethods.KEYEVENTF_KEYUP, UIntPtr.Zero);
                NativeMethods.keybd_event((byte)NativeMethods.VK_CONTROL, 0, NativeMethods.KEYEVENTF_KEYUP, UIntPtr.Zero);

                await Task.Delay(120);

                string? copied = null;
                try { if (System.Windows.Clipboard.ContainsText()) copied = System.Windows.Clipboard.GetText(); } catch { }

                return copied;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Capture] Error: {ex.Message}");
                return null;
            }
        }

        private async Task SolveTextAsync(string rawText)
        {
            if (_isProcessing) return;
            _isProcessing = true;

            try
            {
                Dispatcher.Invoke(() =>
                {
                    StatusBarText.Text = "⚡ Parsing structure and running AI dual-stage verification...";
                    ProcessBtn.IsEnabled = false;
                });

                // 1. Parse Question and Options (Handles bare numbers, JSX/code, unnumbered)
                var parsed = McqParser.Parse(rawText);

                Dispatcher.Invoke(() =>
                {
                    ParsedStemBlock.Text = parsed.Question;
                    if (parsed.Options.Count > 0)
                    {
                        ParsedOptionsBlock.Text = string.Join("\n", parsed.Options.Select(o => $"[{o.Label}] {o.Text}"));
                    }
                    else
                    {
                        ParsedOptionsBlock.Text = "No multiple-choice options identified (General Text).";
                    }
                });

                if (!parsed.IsValidMcq)
                {
                    Dispatcher.Invoke(() =>
                    {
                        StatusBarText.Text = "⚠️ Less than 2 options identified.";
                        KeyResultText.Text = "General Question (Not MCQ)";
                        AiReasoningBlock.Text = "Could not identify at least 2 distinct multiple choice options.";
                    });
                    return;
                }

                // 2. Dual-Stage AI Evaluation
                var result = await _aiSolver.SolveAsync(parsed);
                if (result != null)
                {
                    Dispatcher.Invoke(() =>
                    {
                        KeyResultText.Text = $"KEY RESULT: OPTION {result.AnswerNumber} ({result.AnswerLetter})";
                        AiReasoningBlock.Text = $"Validation Status: {(result.IsVerified ? "VALIDATED" : "UNVERIFIED")}\n" +
                                                $"Caps Lock Blink Count: {result.AnswerNumber} pulse(s)\n\n" +
                                                $"STAGE 1 REASONING:\n{result.Stage1Response}\n\n" +
                                                $"STAGE 2 VERIFICATION:\n{result.Stage2Response}";
                        StatusBarText.Text = $"⚡ Solved: Option {result.AnswerNumber} ({result.AnswerLetter}) | Signaling {result.AnswerNumber} blink(s)...";
                    });

                    // 3. Hardware Caps Lock Blink
                    if (_config.EnableLedSignal)
                    {
                        await _signaler.BlinkAsync(result.AnswerNumber, _config.BlinkDurationMs);
                    }

                    Dispatcher.Invoke(() =>
                    {
                        StatusBarText.Text = $"⚡ Completed: Option {result.AnswerNumber} ({result.AnswerLetter}) signaled via Caps Lock.";
                    });
                }
                else
                {
                    Dispatcher.Invoke(() =>
                    {
                        KeyResultText.Text = "Error in AI evaluation";
                        AiReasoningBlock.Text = "Could not obtain a validated answer from the AI provider. Check your API key in Settings.";
                        StatusBarText.Text = "⚠️ AI Provider returned error or invalid response.";
                    });
                }
            }
            finally
            {
                Dispatcher.Invoke(() =>
                {
                    ProcessBtn.IsEnabled = true;
                });
                _isProcessing = false;
            }
        }

        private void SaveSettings_Click(object sender, RoutedEventArgs e)
        {
            _config.GeminiApiKey = GeminiKeyBox.Text.Trim();
            _config.GeminiModel = GeminiModelBox.Text.Trim();
            if (int.TryParse(BlinkDurationBox.Text.Trim(), out int ms))
            {
                _config.BlinkDurationMs = ms;
            }
            _config.Save();
            System.Windows.MessageBox.Show("Settings saved successfully!", "GodMode", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        private async void TestPulse_Click(object sender, RoutedEventArgs e)
        {
            StatusBarText.Text = "💡 Testing Caps Lock 2-pulse blink...";
            await _signaler.BlinkAsync(2, _config.BlinkDurationMs);
            StatusBarText.Text = "⚡ Test complete. Initial state restored.";
        }
    }
}
