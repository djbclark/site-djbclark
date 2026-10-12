# SIPB LLMs FAQ

> Mirrored from <https://llms.mit.edu/docs/faq>; re-checked against the live page 2026-10-12 (one paragraph added upstream, below).

## How can I use the LLMs?

These servers are available for use by members of the MIT community (i.e., with Touchstone authentication):

- [`LLMS-DEV-1`](https://llms-dev-1.mit.edu)
- [`LLMS-DEV-0`](https://llms-dev-0.mit.edu)

The latter, `LLMS-DEV-0`, is **not** guaranteed to be online. For `LLMS-DEV-1`,
signing in with Touchstone should immediately give access to the models. If you
are a group at MIT (e.g., lab, club) and would like a dedicated login for a
project, please let us know.

By using the LLMs, you agree to use the services respectfully and in good faith —
not for spreading dis/misinformation or for completing your psets, for example.

## Is my information private?

Your submitted prompts and the generated responses never leave the server. Unlike
similar services out there, SIPB LLMs will never sell your data or train machine
learning models. This service was envisioned to respect that.

Submitted prompts and generated responses may be looked at to debug problems with
the service. That data would be looked at in the system logs.

I wrote this up quickly, so this FAQ will be updated over time with clearer information. We will harden our security practices as we write clearer documentation. Email us if you need more info in a pinch.

## What LLMs are available?

We use [Ollama](https://ollama.com) under the hood. If you would like a model
which is available from [the Ollama models library](https://ollama.com/library),
please let us know. We will not install custom models at this time.

Select your model from the dropdown menu at login. Some models are tagged
appropriately. "Vision" models, for example, can accept images as input.

## Why is it taking so long after submitting a prompt?

The GPU can only hold about one model at a time. If it is stalling, either
someone else is generating text, or the server crashed. If the latter, please let
us know.

Keep in mind that uploaded images cannot be greater than some moderate size
([5 MB?](https://github.com/open-webui/open-webui/discussions/3958)) and may fail
silently, which is a limitation of the Open WebUI frontend.

## Can I finetune a model?

No. SIPB LLMs was not intended for finetuning models, only serving existing
permissive-use ones.

## How reliable are the servers?

The `LLMS-DEV-1` server is a "production level" server and is mostly reliable. It
may go down briefly (30 seconds or so) on Fridays around 4-5pm, for updates to the
frontend, a time when most MIT students—a nocturnal species—are sleeping. Longer
outages will be announced to the
[`sipb-llms-users`](https://mailman.mit.edu/mailman/listinfo/sipb-llms-users) list.

Our development level servers are "best effort" and may go down if, e.g., someone
wants to use the GPU to render something in Blender or to play a game using the
server which resides in our office.

There have been instances where the machines freeze, though it happens
infrequently enough that it's not clear the reason. Please use our services
respectfully.

## Something's not working?

Yeah, possibly. We're all doing our best, aren't we? If it's `LLMS-DEV-1`, let us
know your woes at [`sipb-llms@mit.edu`](mailto:sipb-llms@mit.edu) (or `almonds` on
[`matrix.mit.edu`](https://matrix.mit.edu)), and we'll fix things as soon as we
can. If it's `LLMS-DEV-0`, you can visit the SIPB office and see what's up, but
that one's not intended to be online 24/7.

## Is there an API I can use?

Yes. [SIPB's DormSoup](https://dormsoup.mit.edu), in fact, uses the SIPB LLMs API.
The frontend we use for `llms-dev-1` is [Open WebUI](https://docs.openwebui.com/).

Your account's API key can be found in the *Account* pane of the *Settings* menu.
On desktop, click your profile icon in the top right to access *Settings*. Click
*Account*, and then click "show" for *API keys*.

The Open WebUI API is compatible with OpenAI's. It can be used as a drop-in
replacement with [`litellm`](https://github.com/BerriAI/litellm) in Python, for example:

```python
import os

import litellm

os.environ["OPENAI_API_KEY"] = "..."
os.environ["OPENAI_API_BASE"] = "https://llms-dev-1.mit.edu/api"
litellm.set_verbose = True  # optional, but recommended at first

model = "deepseek-r1:32b"
messages = [{
   "content": "Why is critical thinking so important?",
   "role": "user",
}]
response = litellm.completion(
   messages=messages,
   model=f"openai/{model}",
)
content = response.choices[0].message.content
```

For finer control, the available endpoints may be viewed at
[`/docs`](https://llms-dev-1.mit.edu/docs).

## My question isn't here!

Send us an email!
