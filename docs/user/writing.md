# Written guides, briefs and reports

The deck guide, matchup briefs, match reports, the leak finder, the RCQ
guide and the Coach each come with a prompt. Two ways to turn it into
prose, both yours:

- **Copy the prompt** into an assistant you already use, and import the
  answer. The dashboard's card copies the prompt and shows the command
  that reads the answer back, such as `guide --deck KEY --import FILE`;
  `guide` and `brief` also print the prompt with `--prompt`.
- **Set your own Anthropic API key** and press the dashboard's generate
  button instead:

      sensei-top config --set-key -

  It reads the key from standard input. The key is kept in the system
  keyring when there is one, else in the config file, and
  `config --clear-key` removes it.

Nothing calls out without that key and that button press, and the key is
yours: this project runs no service that writes on your behalf. Each call's
cost is measured from the answer and shown beside it. What each button
sends is in [docs/llm.md](../llm.md).

Other providers and local models are on the
[roadmap](../../ROADMAP.md).
