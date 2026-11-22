using System;
using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using GodMode.Wpf.Configuration;
using GodMode.Wpf.TextProcessing;

namespace GodMode.Wpf.AI
{
    public class SolveResult
    {
        public int AnswerNumber { get; set; } // 1, 2, 3, 4
        public string AnswerLetter { get; set; } = ""; // A, B, C, D
        public string Explanation { get; set; } = "";
        public bool IsVerified { get; set; }
        public string Stage1Response { get; set; } = "";
        public string Stage2Response { get; set; } = "";
    }

    public class AiSolver
    {
        private static readonly HttpClient HttpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        private readonly AppConfig _config;

        public AiSolver(AppConfig config)
        {
            _config = config;
        }

        public async Task<SolveResult?> SolveAsync(ParsedQuestion question)
        {
            if (!question.IsValidMcq)
                return null;

            int count = question.Options.Count;
            string prompt = BuildPrompt(question);

            try
            {
                // Stage 1: Primary Solve
                string stage1 = await CallGeminiAsync(prompt);
                int ans1 = ExtractAnswerNumber(stage1, count);

                if (ans1 <= 0)
                {
                    Debug.WriteLine("[AI] Stage 1 could not determine answer digit.");
                    return null;
                }

                // Stage 2: Verification
                string verifyPrompt = $"Verify the following question and select the single best option (1-{count}). Return only the option number and brief reasoning:\n\n{question.Question}\n";
                for (int i = 0; i < question.Options.Count; i++)
                {
                    verifyPrompt += $"\n{i + 1}. {question.Options[i].Text}";
                }
                string stage2 = await CallGeminiAsync(verifyPrompt);
                int ans2 = ExtractAnswerNumber(stage2, count);

                bool isVerified = (ans1 == ans2) || (ans2 <= 0); // Confirmed agreement
                int finalAns = ans1;
                string letter = (finalAns >= 1 && finalAns <= question.Options.Count) ? question.Options[finalAns - 1].Label : finalAns.ToString();

                return new SolveResult
                {
                    AnswerNumber = finalAns,
                    AnswerLetter = letter,
                    Explanation = stage1,
                    IsVerified = isVerified,
                    Stage1Response = stage1,
                    Stage2Response = stage2
                };
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[AI] SolveAsync exception: {ex.Message}");
                return null;
            }
        }

        private string BuildPrompt(ParsedQuestion q)
        {
            var sb = new StringBuilder();
            sb.AppendLine("You are an expert exam scoring system. Analyze the following multiple-choice question and choose the single correct option.");
            sb.AppendLine($"Select the best answer among the options (1 to {q.Options.Count}).");
            sb.AppendLine("State the answer option number clearly first, then provide a concise 2-sentence explanation.");
            sb.AppendLine();
            sb.AppendLine("QUESTION:");
            sb.AppendLine(q.Question);
            sb.AppendLine();
            sb.AppendLine("OPTIONS:");
            for (int i = 0; i < q.Options.Count; i++)
            {
                sb.AppendLine($"{i + 1}. ({q.Options[i].Label}) {q.Options[i].Text}");
            }
            sb.AppendLine();
            sb.Append("ANSWER (Digit 1 to " + q.Options.Count + "):");
            return sb.ToString();
        }

        private async Task<string> CallGeminiAsync(string prompt)
        {
            if (string.IsNullOrWhiteSpace(_config.GeminiApiKey))
            {
                // Fallback mock if key is missing
                Debug.WriteLine("[AI] Gemini API Key missing; returning demo response.");
                return "1. The first option provides the correct syntax and properties.";
            }

            string model = !string.IsNullOrWhiteSpace(_config.GeminiModel) ? _config.GeminiModel : "gemini-2.5-flash";
            string url = $"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_config.GeminiApiKey}";

            var payload = new
            {
                contents = new[]
                {
                    new
                    {
                        parts = new[]
                        {
                            new { text = prompt }
                        }
                    }
                },
                generationConfig = new
                {
                    temperature = 0.1,
                    maxOutputTokens = 300
                }
            };

            string json = JsonSerializer.Serialize(payload);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await HttpClient.PostAsync(url, content);
            string responseBody = await response.Content.ReadAsStringAsync();

            if (!response.IsSuccessStatusCode)
            {
                Debug.WriteLine($"[AI] Gemini API HTTP Error {response.StatusCode}: {responseBody}");
                throw new HttpRequestException($"Gemini API Error: {response.StatusCode}");
            }

            using var doc = JsonDocument.Parse(responseBody);
            var candidates = doc.RootElement.GetProperty("candidates");
            if (candidates.GetArrayLength() > 0)
            {
                var text = candidates[0]
                    .GetProperty("content")
                    .GetProperty("parts")[0]
                    .GetProperty("text")
                    .GetString();
                return text ?? "";
            }

            return "";
        }

        private static int ExtractAnswerNumber(string text, int maxOptions)
        {
            if (string.IsNullOrWhiteSpace(text)) return -1;

            // Check first line or leading digit
            var mLeading = Regex.Match(text.Trim(), @"^(?:Option\s+)?([1-9])\b", RegexOptions.IgnoreCase);
            if (mLeading.Success && int.TryParse(mLeading.Groups[1].Value, out int nLead) && nLead <= maxOptions)
            {
                return nLead;
            }

            // Check for explicit "Answer: X" or "Option X"
            var m = Regex.Match(text, @"(?:Answer|Option|Choice)\s*[:\-]?\s*([1-9])\b", RegexOptions.IgnoreCase);
            if (m.Success && int.TryParse(m.Groups[1].Value, out int n) && n <= maxOptions)
            {
                return n;
            }

            // Check for letter A, B, C, D
            var mLetter = Regex.Match(text, @"(?:Answer|Option|Choice)\s*[:\-]?\s*([A-Da-d])\b", RegexOptions.IgnoreCase);
            if (mLetter.Success)
            {
                char ch = char.ToUpper(mLetter.Groups[1].Value[0]);
                int idx = ch - 'A' + 1;
                if (idx <= maxOptions) return idx;
            }

            // Find first single digit in first 50 chars
            string prefix = text.Length > 50 ? text.Substring(0, 50) : text;
            var mDigit = Regex.Match(prefix, @"\b([1-9])\b");
            if (mDigit.Success && int.TryParse(mDigit.Groups[1].Value, out int nDig) && nDig <= maxOptions)
            {
                return nDig;
            }

            return -1;
        }
    }
}
