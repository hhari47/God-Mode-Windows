using System;
using System.IO;
using System.Text.Json;

namespace GodMode.Wpf.Configuration
{
    public class AppConfig
    {
        public string GeminiApiKey { get; set; } = "";
        public string GeminiModel { get; set; } = "gemini-3.5-flash-lite";
        public string GrokApiKey { get; set; } = "";
        public string GrokModel { get; set; } = "grok-2-latest";
        public string AiProvider { get; set; } = "gemini";
        public bool EnableLedSignal { get; set; } = true;
        public int BlinkDurationMs { get; set; } = 250;
        public bool MinimizeToTray { get; set; } = true;
        public bool StartMinimized { get; set; } = false;
        public string TesseractPath { get; set; } = @"C:\Program Files\Tesseract-OCR\tesseract.exe";

        private static readonly string ConfigPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "GodMode",
            "config.json"
        );

        public static AppConfig Load()
        {
            var config = new AppConfig();

            // 1. Try reading .env in current or parent directory
            LoadDotEnv(config);

            // 2. Try reading AppData config.json
            if (File.Exists(ConfigPath))
            {
                try
                {
                    string json = File.ReadAllText(ConfigPath);
                    var loaded = JsonSerializer.Deserialize<AppConfig>(json);
                    if (loaded != null)
                    {
                        if (!string.IsNullOrWhiteSpace(loaded.GeminiApiKey)) config.GeminiApiKey = loaded.GeminiApiKey;
                        if (!string.IsNullOrWhiteSpace(loaded.GeminiModel)) config.GeminiModel = loaded.GeminiModel;
                        if (!string.IsNullOrWhiteSpace(loaded.GrokApiKey)) config.GrokApiKey = loaded.GrokApiKey;
                        if (!string.IsNullOrWhiteSpace(loaded.AiProvider)) config.AiProvider = loaded.AiProvider;
                        config.EnableLedSignal = loaded.EnableLedSignal;
                        config.BlinkDurationMs = loaded.BlinkDurationMs;
                        config.MinimizeToTray = loaded.MinimizeToTray;
                    }
                }
                catch { }
            }

            return config;
        }

        public void Save()
        {
            try
            {
                string dir = Path.GetDirectoryName(ConfigPath)!;
                if (!Directory.Exists(dir))
                    Directory.CreateDirectory(dir);

                string json = JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(ConfigPath, json);
            }
            catch { }
        }

        private static void LoadDotEnv(AppConfig config)
        {
            string[] paths = {
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".env"),
                Path.Combine(Directory.GetCurrentDirectory(), ".env"),
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", "..", "..", ".env")
            };

            foreach (var p in paths)
            {
                if (File.Exists(p))
                {
                    foreach (var line in File.ReadAllLines(p))
                    {
                        var trimmed = line.Trim();
                        if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith("#")) continue;
                        int idx = trimmed.IndexOf('=');
                        if (idx > 0)
                        {
                            string key = trimmed.Substring(0, idx).Trim();
                            string val = trimmed.Substring(idx + 1).Trim();
                            switch (key.ToUpperInvariant())
                            {
                                case "GEMINI_API_KEY": config.GeminiApiKey = val; break;
                                case "GEMINI_MODEL": config.GeminiModel = val; break;
                                case "GROK_API_KEY": config.GrokApiKey = val; break;
                                case "GROK_MODEL": config.GrokModel = val; break;
                                case "AI_PROVIDER": config.AiProvider = val; break;
                                case "ENABLE_LED_SIGNAL": config.EnableLedSignal = val.Equals("true", StringComparison.OrdinalIgnoreCase); break;
                                case "BLINK_DURATION_MS": if (int.TryParse(val, out int ms)) config.BlinkDurationMs = ms; break;
                                case "MINIMIZE_TO_TRAY": config.MinimizeToTray = val.Equals("true", StringComparison.OrdinalIgnoreCase); break;
                                case "START_MINIMIZED": config.StartMinimized = val.Equals("true", StringComparison.OrdinalIgnoreCase); break;
                                case "TESSERACT_PATH": config.TesseractPath = val; break;
                            }
                        }
                    }
                    break;
                }
            }
        }
    }
}
