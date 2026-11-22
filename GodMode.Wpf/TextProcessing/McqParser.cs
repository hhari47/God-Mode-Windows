using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace GodMode.Wpf.TextProcessing
{
    public class QuestionOption
    {
        public string Label { get; set; } = "";
        public string Text { get; set; } = "";
        public int OriginalIndex { get; set; }
        public int OptionNumber => OriginalIndex + 1;
    }

    public class ParsedQuestion
    {
        public string Question { get; set; } = "";
        public List<QuestionOption> Options { get; set; } = new();
        public bool IsMultipleChoice { get; set; }
        public string RawText { get; set; } = "";

        public int OptionCount => Options.Count;
        public bool IsValidMcq => IsMultipleChoice && Options.Count >= 2 && Options.All(o => !string.IsNullOrWhiteSpace(o.Text));
    }

    public static class McqParser
    {
        private static readonly Regex OptionLineRegex = new Regex(
            @"^[\s]*(?:(?:\([xX\s✓✔]?\)|\[[xX\s✓✔]?\]|[•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3}))?\s*" +
            @"(?:\*\*|\*|__|_)?(?:(?:Option|Choice|Item|Answer|Selection)\s+)?" +
            @"(?:" +
                @"\((?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\)|" +
                @"\[(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\]|" +
                @"(?:\*\*|\*|__|_)?(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—])\s*|" +
                @"(?:(?:Option|Choice|Item|Answer|Selection)\s+)(?:\*\*|\*|__|_)?(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—]\s*|\s+(?=\S))|" +
                @"(?<label>[1-9][0-9]?)(?:\s+(?=[A-Za-z0-9\""'\(\[<@\$/`]|-(?=[A-Za-z\-_]))|(?=[A-Za-z\""'\(\[{<@\$/`]|-(?=[A-Za-z\-_])))" +
            @")" +
            @"(?:\*\*|\*|__|_)?\s*(?<rest>.*)$",
            RegexOptions.Compiled
        );

        private static readonly Regex StandaloneLabelRegex = new Regex(
            @"^[\s]*(?:(?:\([xX\s✓✔]?\)|\[[xX\s✓✔]?\]|(?:[•·⁃◦▪▫–—\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3}|\-(?=\s))))?\s*" +
            @"(?:\*\*|\*|__|_)?(?:" +
                @"(?:Option|Choice|Item|Answer|Selection)\s+(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})|" +
                @"\((?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\)|" +
                @"\[(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\]|" +
                @"(?:\*\*|\*|__|_)?(?<label>[A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—])|" +
                @"(?<bare_label>[1-9][0-9]?|[A-Za-z])" +
            @")[\s]*$",
            RegexOptions.Compiled
        );

        private static readonly string[] Labels = { "A", "B", "C", "D", "E", "F", "G", "H", "I", "J" };

        public static ParsedQuestion Parse(string rawInput)
        {
            if (string.IsNullOrWhiteSpace(rawInput))
            {
                return new ParsedQuestion { RawText = rawInput ?? "" };
            }

            string text = rawInput.Trim().Replace("\r\n", "\n").Replace("\r", "\n");
            var lines = text.Split('\n');

            var stemLines = new List<string>();
            var parsedOptions = new List<QuestionOption>();
            string? currentLabel = null;
            var currentOptionLines = new List<string>();
            int? nextExpectedNum = null;
            char? nextExpectedChar = null;

            for (int i = 0; i < lines.Length; i++)
            {
                string lineTrimmed = lines[i].Trim();
                if (string.IsNullOrEmpty(lineTrimmed))
                {
                    if (currentLabel != null) currentOptionLines.Add("");
                    else stemLines.Add("");
                    continue;
                }

                var match = MatchOptionPrefix(lineTrimmed, nextExpectedNum, nextExpectedChar);
                if (match != null)
                {
                    // Flush previous
                    if (currentLabel != null)
                    {
                        string optText = string.Join("\n", currentOptionLines).Trim();
                        int idx = parsedOptions.Count;
                        string lbl = idx < Labels.Length ? Labels[idx] : (idx + 1).ToString();
                        parsedOptions.Add(new QuestionOption
                        {
                            Label = lbl,
                            Text = optText,
                            OriginalIndex = idx
                        });
                        currentOptionLines.Clear();
                    }

                    currentLabel = match.Label;
                    if (!string.IsNullOrEmpty(match.Rest))
                    {
                        currentOptionLines.Add(match.Rest);
                    }

                    if (int.TryParse(match.Label, out int n))
                    {
                        nextExpectedNum = n + 1;
                        nextExpectedChar = null;
                    }
                    else if (match.Label.Length == 1 && char.IsLetter(match.Label[0]))
                    {
                        nextExpectedChar = (char)(char.ToUpper(match.Label[0]) + 1);
                        nextExpectedNum = null;
                    }
                }
                else if (currentLabel != null)
                {
                    currentOptionLines.Add(lineTrimmed);
                }
                else
                {
                    stemLines.Add(lineTrimmed);
                }
            }

            // Flush last
            if (currentLabel != null)
            {
                string optText = string.Join("\n", currentOptionLines).Trim();
                int idx = parsedOptions.Count;
                string lbl = idx < Labels.Length ? Labels[idx] : (idx + 1).ToString();
                parsedOptions.Add(new QuestionOption
                {
                    Label = lbl,
                    Text = optText,
                    OriginalIndex = idx
                });
            }

            // If parsedOptions are empty strings (e.g. unnumbered options)
            if (parsedOptions.Count > 0 && parsedOptions.All(o => string.IsNullOrWhiteSpace(o.Text)))
            {
                parsedOptions.Clear();
            }

            // Fallback: unnumbered lines
            if (parsedOptions.Count < 2)
            {
                var unnumbered = ParseUnnumberedLines(text);
                if (unnumbered != null)
                {
                    return unnumbered;
                }
            }

            string stem = string.Join("\n", stemLines).Trim();
            return new ParsedQuestion
            {
                Question = string.IsNullOrEmpty(stem) ? "Please select the correct option:" : stem,
                Options = parsedOptions,
                IsMultipleChoice = parsedOptions.Count >= 2,
                RawText = rawInput
            };
        }

        private class PrefixMatch
        {
            public string Label { get; set; } = "";
            public string Rest { get; set; } = "";
        }

        private static PrefixMatch? MatchOptionPrefix(string line, int? nextExpectedNum, char? nextExpectedChar)
        {
            // 1. Standard option line regex with named groups
            var m1 = OptionLineRegex.Match(line);
            if (m1.Success && m1.Groups["label"].Success && !string.IsNullOrEmpty(m1.Groups["label"].Value))
            {
                string label = m1.Groups["label"].Value;
                string rest = m1.Groups["rest"].Value.Trim();
                return new PrefixMatch { Label = label, Rest = rest };
            }

            // 2. Standalone label regex with named groups
            var m2 = StandaloneLabelRegex.Match(line);
            if (m2.Success)
            {
                string label = "";
                bool isBare = false;

                if (m2.Groups["label"].Success && !string.IsNullOrEmpty(m2.Groups["label"].Value))
                {
                    label = m2.Groups["label"].Value;
                }
                else if (m2.Groups["bare_label"].Success && !string.IsNullOrEmpty(m2.Groups["bare_label"].Value))
                {
                    label = m2.Groups["bare_label"].Value;
                    isBare = true;
                }

                if (!string.IsNullOrEmpty(label))
                {
                    if (isBare)
                    {
                        if (int.TryParse(label, out int num))
                        {
                            if (nextExpectedNum == null && num != 1) return null;
                            if (nextExpectedNum != null && num != nextExpectedNum.Value) return null;
                        }
                        else if (label.Length == 1 && char.IsLetter(label[0]))
                        {
                            char ch = char.ToUpper(label[0]);
                            if (nextExpectedChar == null && ch != 'A') return null;
                            if (nextExpectedChar != null && ch != nextExpectedChar.Value) return null;
                        }
                    }
                    return new PrefixMatch { Label = label, Rest = "" };
                }
            }

            return null;
        }

        private static ParsedQuestion? ParseUnnumberedLines(string text)
        {
            var rawLines = text.Split('\n').Select(l => l.Trim()).Where(l => !string.IsNullOrEmpty(l)).ToList();
            if (rawLines.Count < 3) return null;

            int qIdx = rawLines.FindLastIndex(l => l.Contains("?"));
            if (qIdx >= 0 && qIdx < rawLines.Count - 1)
            {
                var opts = rawLines.Skip(qIdx + 1).ToList();
                if (opts.Count >= 2 && opts.Count <= 6)
                {
                    var optObjs = opts.Select((t, i) => new QuestionOption
                    {
                        Label = i < Labels.Length ? Labels[i] : (i + 1).ToString(),
                        Text = t,
                        OriginalIndex = i
                    }).ToList();

                    return new ParsedQuestion
                    {
                        Question = string.Join("\n", rawLines.Take(qIdx + 1)),
                        Options = optObjs,
                        IsMultipleChoice = true,
                        RawText = text
                    };
                }
            }
            return null;
        }
    }
}
