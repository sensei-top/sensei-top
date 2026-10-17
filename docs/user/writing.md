# Written guides, briefs and reports

The deck guide, matchup briefs, match reports, the leak finder, the RCQ
guide and the Coach each come with a prompt. Two ways to turn it into
prose, both yours:

- **Copy the prompt** into an assistant you already use, then paste its
  whole answer into the box under the prompt and press **Save the
  answer**. The answer starts with a `for` line naming the card it was
  written for, so an answer pasted into the wrong card is refused, with a
  sentence saying where it belongs, and nothing is stored; if the line is
  missing, copy that card's prompt again. A pasted answer shows as
  "Pasted in." and costs nothing. Running from source, the guide and
  brief cards also show the command that saves an answer from a file,
  such as `guide --deck KEY --import FILE`; `guide` and `brief` print the
  prompt with `--prompt`.
- **Set your own Anthropic API key** and press the dashboard's generate
  button instead. A matchup brief has no button of its own: generating
  its deck's guide writes the deck's briefs too.

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
