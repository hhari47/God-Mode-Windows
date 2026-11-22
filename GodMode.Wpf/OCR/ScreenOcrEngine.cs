using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;

namespace GodMode.Wpf.OCR
{
    public class TextObservation
    {
        public string Text { get; set; } = "";
        public float X { get; set; }
        public float Y { get; set; }
        public float Width { get; set; }
        public float Height { get; set; }
        public float MaxX => X + Width;
        public float MaxY => Y + Height;

        public float VerticalOverlapFraction(TextObservation other)
        {
            float overlap = Math.Max(0.0f, Math.Min(MaxY, other.MaxY) - Math.Max(Y, other.Y));
            float smaller = Math.Min(Height, other.Height);
            return smaller > 0.0f ? overlap / smaller : 0.0f;
        }

        public float HorizontalOverlapFraction(TextObservation other)
        {
            float overlap = Math.Max(0.0f, Math.Min(MaxX, other.MaxX) - Math.Max(X, other.X));
            float narrower = Math.Min(Width, other.Width);
            return narrower > 0.0f ? overlap / narrower : 0.0f;
        }
    }

    public static class ScreenOcrEngine
    {
        private const float LINE_OVERLAP_THRESHOLD = 0.5f;
        private const float COLUMN_OVERLAP_THRESHOLD = 0.25f;

        public static async Task<string?> CaptureScreenAndOcrAsync()
        {
            try
            {
                // Capture active window or primary screen
                IntPtr hwnd = NativeMethods.GetForegroundWindow();
                Rectangle bounds;
                if (hwnd != IntPtr.Zero && NativeMethods.GetWindowRect(hwnd, out var rect) && rect.Width > 100 && rect.Height > 100)
                {
                    bounds = new Rectangle(rect.Left, rect.Top, rect.Width, rect.Height);
                }
                else
                {
                    bounds = System.Windows.Forms.Screen.PrimaryScreen?.Bounds ?? new Rectangle(0, 0, 1920, 1080);
                }

                using var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
                using (var g = Graphics.FromImage(bitmap))
                {
                    g.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size);
                }

                return await OcrBitmapAsync(bitmap);
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[OCR] CaptureScreenAndOcr error: {ex.Message}");
                return null;
            }
        }

        public static async Task<string?> OcrBitmapAsync(Bitmap bitmap)
        {
            try
            {
                // Convert System.Drawing.Bitmap to WinRT SoftwareBitmap
                using var ms = new MemoryStream();
                bitmap.Save(ms, ImageFormat.Bmp);
                ms.Position = 0;

                using var randomAccessStream = new InMemoryRandomAccessStream();
                using var writer = new DataWriter(randomAccessStream.GetOutputStreamAt(0));
                writer.WriteBytes(ms.ToArray());
                await writer.StoreAsync();

                var decoder = await BitmapDecoder.CreateAsync(randomAccessStream);
                var softwareBitmap = await decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied);

                var ocrEngine = OcrEngine.TryCreateFromUserProfileLanguages() ?? OcrEngine.TryCreateFromLanguage(new Windows.Globalization.Language("en-US"));
                if (ocrEngine == null)
                {
                    Debug.WriteLine("[OCR] Windows Native OcrEngine not available on this system.");
                    return null;
                }

                var ocrResult = await ocrEngine.RecognizeAsync(softwareBitmap);
                if (ocrResult == null || ocrResult.Lines.Count == 0)
                {
                    return null;
                }

                // Extract word observations with coordinates
                var observations = new List<TextObservation>();
                foreach (var line in ocrResult.Lines)
                {
                    foreach (var word in line.Words)
                    {
                        var rect = word.BoundingRect;
                        observations.Add(new TextObservation
                        {
                            Text = word.Text,
                            X = (float)rect.X,
                            Y = (float)rect.Y,
                            Width = (float)rect.Width,
                            Height = (float)rect.Height
                        });
                    }
                }

                // Reconstruct text using geometric ReadingOrder
                return ReconstructReadingOrder(observations);
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[OCR] OcrBitmapAsync error: {ex.Message}");
                return null;
            }
        }

        private static string ReconstructReadingOrder(List<TextObservation> observations)
        {
            if (observations.Count == 0) return "";
            if (observations.Count == 1) return observations[0].Text;

            // Group into column clusters
            var clusters = new List<List<TextObservation>>();
            foreach (var obs in observations.OrderBy(o => o.X))
            {
                var matched = clusters.FirstOrDefault(c => c.Any(existing => existing.HorizontalOverlapFraction(obs) >= COLUMN_OVERLAP_THRESHOLD));
                if (matched != null)
                {
                    matched.Add(obs);
                }
                else
                {
                    clusters.Add(new List<TextObservation> { obs });
                }
            }

            var resultLines = new List<string>();
            foreach (var col in clusters.OrderBy(c => c.Min(o => o.X)))
            {
                // Group column into lines top-to-bottom
                var lines = new List<List<TextObservation>>();
                foreach (var obs in col.OrderBy(o => o.Y))
                {
                    if (lines.Count > 0 && lines[^1][0].VerticalOverlapFraction(obs) >= LINE_OVERLAP_THRESHOLD)
                    {
                        lines[^1].Add(obs);
                    }
                    else
                    {
                        lines.Add(new List<TextObservation> { obs });
                    }
                }

                foreach (var line in lines.OrderBy(l => l.Min(o => o.Y)))
                {
                    var lineText = string.Join(" ", line.OrderBy(o => o.X).Select(o => o.Text));
                    if (!string.IsNullOrWhiteSpace(lineText))
                    {
                        resultLines.Add(lineText);
                    }
                }
            }

            return string.Join("\n", resultLines);
        }
    }
}
