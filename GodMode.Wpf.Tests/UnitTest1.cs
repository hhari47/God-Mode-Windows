using System;
using Xunit;
using GodMode.Wpf.TextProcessing;
using GodMode.Wpf.Configuration;
using GodMode.Wpf.Signaling;

namespace GodMode.Wpf.Tests
{
    public class McqParserTests
    {
        [Fact]
        public void TestNextJsBareSequentialNumbers()
        {
            string input = @"Which line correctly links to the /contact page using Next.js?

1
<Link to=""/contact"">Contact</Link>
2
<a page=""/contact"">Contact</a>
3
<Link href=""/contact"">Contact</Link>
4
<Link route=""/contact"">Contact</Link>";

            var parsed = McqParser.Parse(input);

            Assert.True(parsed.IsValidMcq);
            Assert.Equal(4, parsed.Options.Count);
            Assert.Contains("Which line correctly links to the /contact page using Next.js?", parsed.Question);
            Assert.Equal("A", parsed.Options[0].Label);
            Assert.Equal(@"<Link to=""/contact"">Contact</Link>", parsed.Options[0].Text);
            Assert.Equal("B", parsed.Options[1].Label);
            Assert.Equal(@"<a page=""/contact"">Contact</a>", parsed.Options[1].Text);
            Assert.Equal("C", parsed.Options[2].Label);
            Assert.Equal(@"<Link href=""/contact"">Contact</Link>", parsed.Options[2].Text);
            Assert.Equal("D", parsed.Options[3].Label);
            Assert.Equal(@"<Link route=""/contact"">Contact</Link>", parsed.Options[3].Text);
        }

        [Fact]
        public void TestStandardLetterOptions()
        {
            string input = @"What is the capital of France?
A) London
B) Paris
C) Berlin
D) Madrid";

            var parsed = McqParser.Parse(input);

            Assert.True(parsed.IsValidMcq);
            Assert.Equal(4, parsed.Options.Count);
            Assert.Equal("London", parsed.Options[0].Text);
            Assert.Equal("Paris", parsed.Options[1].Text);
        }

        [Fact]
        public void TestUnnumberedLinesFallback()
        {
            string input = @"What is 2 + 2?
3
4
5
6";

            var parsed = McqParser.Parse(input);

            Assert.True(parsed.IsValidMcq);
            Assert.Equal(4, parsed.Options.Count);
        }

        [Fact]
        public void TestAppConfigDefaults()
        {
            var config = AppConfig.Load();
            Assert.NotNull(config);
            Assert.True(config.BlinkDurationMs > 0);
        }

        [Fact]
        public void TestCapsLockStateQuery()
        {
            bool state = CapsLockSignaler.GetCapsLockState();
            // Should execute without throwing
            Assert.True(state || !state);
        }
    }
}
