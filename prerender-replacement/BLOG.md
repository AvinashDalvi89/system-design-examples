# How I Replaced Prerender.io with My Own Serverless Renderer on AWS — For ₹0/Month

## The Problem That Started It All

I was paying ₹5,000/month for prerender.io.

My app is an Angular SPA hosted on AWS Amplify. Angular renders everything client-side using JavaScript. Social bots like WhatsApp, LinkedIn, Googlebot, and Telegram don't execute JavaScript. They crawl your URL, get a blank HTML shell, and your link preview shows nothing. No title. No image. No description.

Prerender.io solves this by running a headless browser on their servers, rendering your page, and returning the fully-rendered HTML to bots. It works well. But at ₹5,000/month, I was paying for a service that was essentially idling — my platform was still early stage, getting very little traffic while I worked on getting traction.

That's ₹5,000/month for almost zero usage. No scaling. No pay-per-use. Just a flat fee.

I started asking: can I build this myself on AWS and pay only for what I actually use?

---

## Understanding the Existing Setup

Before building anything, I needed to understand exactly what prerender.io was doing for me. The architecture was:

```
Bot request
    ↓
CloudFront (custom distribution)
    ↓
Lambda@Edge — viewer-request trigger
    detects bot via User-Agent regex
    sets x-prerender-token, x-prerender-host headers
    ↓
Lambda@Edge — origin-request trigger
    sees those headers → changes origin to service.prerender.io
    ↓
prerender.io renders the Angular page and returns HTML
```

Regular users bypass all of this entirely and hit Amplify directly.

The key insight: **prerender.io was just a CloudFront origin**. The Lambda@Edge was doing the bot detection and routing. prerender.io itself was a black box sitting at the end of that route.

If I could replace that black box with my own renderer, I wouldn't need to touch the bot detection logic at all.

---

## Designing the Replacement

The requirements were clear:
- Serverless — pay only when a bot actually hits a page
- No fixed monthly cost
- Same output as prerender.io — fully rendered HTML
- No changes to the Angular app
- Minimal changes to the bot detection logic in Lambda@Edge

### The Core Idea

```
Replace this:
  Lambda@Edge origin-request → service.prerender.io

With this:
  Lambda@Edge origin-request → our own renderer Lambda
                                    ↓
                               Check S3 cache
                               Hit  → return HTML (~300ms)
                               Miss → Puppeteer renders Angular page
                                      store in S3
                                      return HTML (~5-8s)
```

### Why Puppeteer + `networkidle0`?

Prerender.io works without any changes to the Angular app. It uses a headless Chrome browser that waits until the page has no network activity for 500ms (`networkidle0`). This gives Angular enough time to finish fetching data and rendering the DOM. The same approach works in our own Lambda — no Angular code changes needed.

### Why S3 for Caching?

A rendered page doesn't change every second. An article published today will have the same meta tags tomorrow. Caching the rendered HTML in S3 means:
- First bot request for a URL: Puppeteer renders it (5–10 seconds, acceptable for bots)
- Every subsequent bot request: S3 returns it in ~300ms
- Cache TTL: 24 hours (configurable)

---

## Architecture

```
Bot hits myapp.com/article/my-article
    ↓
CloudFront
    ↓
Lambda@Edge viewer-request — socialbots function
    WhatsApp / Googlebot / LinkedIn detected via User-Agent regex
    Sets x-prerender-token, x-prerender-host on request headers
    ↓
Lambda@Edge origin-request — socialbots function
    Sees x-prerender-token header → it's a bot
    Explicitly sets Host header to precache.myapp.com  ← critical fix
    Changes origin to precache.myapp.com
    ↓
API Gateway HTTP API (ap-south-1)
    ↓
my-renderer Lambda (Node.js container, 2048MB, 30s)
    ↓
S3 cache check — my-prerender-cache
    ├── HIT  (rendered-at < 24h) → return HTML in ~300ms
    └── MISS → Puppeteer opens https://myapp.com/article/my-article
               waits networkidle0 (Angular fully renders)
               stores HTML in S3 with rendered-at timestamp
               returns HTML in ~5-8s

Regular users → Amplify directly (completely unchanged)
```

---

## The Code

### Lambda@Edge — `socialbots` function

This runs at CloudFront edge. The key change from the original prerender.io version is the last 5 lines of the origin-request block. Bot detection logic is untouched.

```javascript
'use strict';

const INTERNAL_TOKEN = 'your-secret-token'; // same value as renderer Lambda INTERNAL_TOKEN env var

exports.handler = (event, context, callback) => {
    const request = event.Records[0].cf.request;

    if (request.headers['x-prerender-token'] && request.headers['x-prerender-host']) {
        // ── ORIGIN-REQUEST: bot detected in viewer-request, now route to renderer ──

        if (request.headers['x-query-string']) {
            request.querystring = request.headers['x-query-string'][0].value;
        }

        // CRITICAL: When Lambda@Edge changes request.origin, CloudFront does NOT
        // automatically update the Host header. API Gateway rejects requests where
        // Host doesn't match its configured custom domain → ForbiddenException.
        // Must set Host explicitly before setting request.origin.
        request.headers['host'] = [{ key: 'Host', value: 'precache.myapp.com' }];

        request.origin = {
            custom: {
                domainName: 'precache.myapp.com', // ← was: service.prerender.io
                port: 443,
                protocol: 'https',
                readTimeout: 30,                           // ← was: 20 (Puppeteer needs up to 25s)
                keepaliveTimeout: 5,
                customHeaders: {
                    'x-prerender-token': [{                // auth token sent to renderer
                        key: 'X-Prerender-Token',
                        value: INTERNAL_TOKEN
                    }]
                },
                sslProtocols: ['TLSv1.2'],                 // ← was: TLSv1, TLSv1.1 (deprecated)
                path: ''                                   // ← was: '/https%3A%2F%2F' + host
            }
        };

    } else {
        // ── VIEWER-REQUEST: detect bots, set headers ── (completely unchanged)
        const headers = request.headers;
        const user_agent = headers['user-agent'];
        const host = headers['host'];

        if (user_agent && host) {
            var prerender = /googlebot|adsbot\-google|Feedfetcher\-Google|bingbot|yandex|
                baiduspider|Facebot|facebookexternalhit|twitterbot|rogerbot|linkedinbot|
                embedly|quora link preview|showyoubot|outbrain|pinterest|slackbot|vkShare|
                W3C_Validator|redditbot|applebot|whatsapp|flipboard|tumblr|bitlybot|
                skypeuripreview|nuzzel|discordbot|google page speed|qwantify|pinterestbot|
                bitrix link preview|xing\-contenttabreceiver|chrome\-lighthouse|telegrambot|
                Perplexity|OAI-SearchBot|ChatGPT|GPTBot|ClaudeBot|Amazonbot|
                integration-test/i.test(user_agent[0].value);

            prerender = prerender || /_escaped_fragment_/.test(request.querystring);
            prerender = prerender && !/\.(js|css|xml|less|png|jpg|jpeg|gif|pdf|doc|txt|
                ico|rss|zip|mp3|rar|exe|wmv|avi|ppt|mpg|mpeg|tif|wav|mov|psd|ai|xls|
                mp4|m4a|swf|dat|dmg|iso|flv|m4v|torrent|ttf|woff|svg|eot)$/i
                .test(request.uri);

            if (prerender) {
                console.log('Bot detected:', user_agent[0].value);
                headers['x-prerender-token'] = [{ key: 'X-Prerender-Token', value: INTERNAL_TOKEN }];
                headers['x-prerender-host'] = [{ key: 'X-Prerender-Host', value: host[0].value }];
                headers['x-prerender-cachebuster'] = [{ key: 'X-Prerender-Cachebuster', value: Date.now().toString() }];
                headers['x-query-string'] = [{ key: 'X-Query-String', value: request.querystring }];
            }
        }
    }

    callback(null, request);
};
```

> **Deploy note**: Lambda@Edge must be in `us-east-1`. After publishing a new version, update both the viewer-request and origin-request ARNs in your CloudFront behavior to point to the new version number (e.g. `:12` → `:13`). CloudFront takes 5–10 minutes to propagate.

---

### Renderer Lambda — `index.js`

This runs in `ap-south-1` as a container image. Receives bot requests from API Gateway, checks S3 cache, renders with Puppeteer if needed.

```javascript
'use strict';

const chromium = require('@sparticuz/chromium');
const puppeteer = require('puppeteer-core');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const s3 = new S3Client({});

const BUCKET         = process.env.CACHE_BUCKET;
const CACHE_TTL_MS   = parseInt(process.env.CACHE_TTL_HOURS || '24') * 3600 * 1000;
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN;
const SITE_URL       = process.env.SITE_URL || 'https://myapp.com';

// Reuse browser across warm Lambda invocations — saves 3-5s Chromium startup time
let browser = null;

async function getBrowser() {
    if (browser && browser.connected) return browser;
    browser = await puppeteer.launch({
        args: chromium.args,
        defaultViewport: { width: 1280, height: 800 },
        executablePath: await chromium.executablePath(),
        headless: true,
    });
    return browser;
}

function pathToS3Key(urlPath) {
    const clean = urlPath.replace(/^\/+|\/+$/g, '') || 'index';
    return `cache/${clean}.html`;
    // Examples:
    //   /article/my-slug  →  cache/article/my-slug.html
    //   /                 →  cache/index.html
}

exports.handler = async (event) => {
    const headers = event.headers || {};

    // Reject requests without the internal token
    // (prevents anyone who discovers the URL from triggering renders)
    if (INTERNAL_TOKEN) {
        const token = headers['x-prerender-token'] || headers['x-internal-token'];
        if (token !== INTERNAL_TOKEN) {
            console.log('Rejected: wrong or missing token');
            return { statusCode: 403, body: 'Forbidden' };
        }
    }

    const urlPath   = event.rawPath || '/';
    const host      = headers['x-prerender-host'] || new URL(SITE_URL).hostname;
    const targetUrl = `https://${host}${urlPath}`;
    const s3Key     = pathToS3Key(urlPath);

    // ── 1. Check S3 cache ─────────────────────────────────────────────────────
    try {
        const cached     = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: s3Key }));
        const renderedAt = parseInt(cached.Metadata?.['rendered-at'] || '0');

        if ((Date.now() - renderedAt) < CACHE_TTL_MS) {
            const html = await cached.Body.transformToString('utf-8');
            console.log(`CACHE HIT [${urlPath}]`);
            return {
                statusCode: 200,
                headers: {
                    'content-type': 'text/html; charset=utf-8',
                    'x-prerender-cache': 'HIT',
                },
                body: html,
            };
        }
        console.log(`CACHE STALE [${urlPath}] — re-rendering`);
    } catch (err) {
        if (err.name !== 'NoSuchKey') console.error('S3 read error:', err.message);
        console.log(`CACHE MISS [${urlPath}]`);
    }

    // ── 2. Render with Puppeteer ──────────────────────────────────────────────
    console.log(`Rendering: ${targetUrl}`);

    let html;
    try {
        const b    = await getBrowser();
        const page = await b.newPage();

        // Block images, fonts, media — bots only need HTML + meta tags.
        // Blocking these cuts render time by 30-60%.
        await page.setRequestInterception(true);
        page.on('request', req =>
            ['image', 'font', 'media'].includes(req.resourceType())
                ? req.abort()
                : req.continue()
        );

        // networkidle0: wait until no network activity for 500ms.
        // This is how prerender.io works — Angular finishes data fetching and rendering.
        await page.goto(targetUrl, { waitUntil: 'networkidle0', timeout: 25000 });

        html = await page.content();
        await page.close();

    } catch (err) {
        console.error(`Render failed [${targetUrl}]:`, err.message);
        if (browser) {
            try { await browser.close(); } catch (_) {}
            browser = null; // force fresh browser on next invocation
        }
        return { statusCode: 500, body: 'Render error' };
    }

    // ── 3. Store in S3 cache ──────────────────────────────────────────────────
    try {
        await s3.send(new PutObjectCommand({
            Bucket: BUCKET,
            Key: s3Key,
            Body: html,
            ContentType: 'text/html; charset=utf-8',
            Metadata: {
                'rendered-at': Date.now().toString(),
                'source-url': targetUrl,
            },
        }));
        console.log(`Cached → ${s3Key}`);
    } catch (err) {
        console.error('S3 write error (non-fatal):', err.message);
    }

    return {
        statusCode: 200,
        headers: {
            'content-type': 'text/html; charset=utf-8',
            'x-prerender-cache': 'MISS',
        },
        body: html,
    };
};
```

### Dockerfile

```dockerfile
# AWS Lambda Node.js 20 base image (Amazon Linux 2023)
# @sparticuz/chromium v133+ is compatible with AL2023
FROM public.ecr.aws/lambda/nodejs:20

COPY package.json ./
RUN npm install --omit=dev

COPY index.js ./

CMD ["index.handler"]
```

### `package.json`

```json
{
  "name": "prerender-renderer",
  "version": "1.0.0",
  "dependencies": {
    "@aws-sdk/client-s3": "^3.741.0",
    "@sparticuz/chromium": "^133.0.0",
    "puppeteer-core": "^24.0.0"
  }
}
```

> **Build note**: Always build with `--platform linux/amd64 --provenance=false` on Mac. The `--provenance=false` flag prevents Docker Desktop from creating an OCI manifest list, which Lambda doesn't support.
> ```bash
> docker build --platform linux/amd64 --provenance=false -t renderer .
> ```

---

## Problems We Hit Along the Way

### Problem 1: Lambda Block Public Access (Account-Level)

The renderer Lambda needed an HTTP endpoint CloudFront could call as a custom origin. The natural choice was **Lambda Function URL** — no extra services, free, simple.

It returned 403 immediately.

AWS silently enabled **Lambda Block Public Access** at the account level in late 2024 (similar to S3's public access block). This blocks all Lambda Function URLs from public internet access, even with `AuthType=NONE`. The feature exists for good reasons but wasn't clearly communicated as a default.

**Fix**: Use **API Gateway HTTP API** instead. Same effective cost (< $1/month at any realistic scale for this use case), no public access restrictions.

### Problem 2: The Host Header

This was the hardest bug to diagnose. Symptoms:
- Direct request to `precache.myapp.com` with token → 200 ✓
- Bot request through CloudFront → 403 from API Gateway
- Response had `x-amzn-errortype: ForbiddenException` and `content-length: 0`

The `content-length: 0` was the clue. Our Lambda's 403 returns body `"Forbidden"` (8 bytes). Zero content means the request **never reached our Lambda** — API Gateway itself was rejecting it.

Root cause: when Lambda@Edge dynamically changes `request.origin`, **CloudFront does not update the `Host` header** to match the new origin domain. The request arrives at API Gateway with `Host: myapp.com` instead of `Host: precache.myapp.com`. API Gateway rejects it because that host isn't mapped to any API.

Confirmed with:
```bash
# Simulates what CloudFront sends without the fix
curl -H "Host: myapp.com" https://YOUR_API_ID.execute-api.ap-south-1.amazonaws.com/
# → 403 ForbiddenException

# Correct Host
curl -H "Host: precache.myapp.com" https://YOUR_API_ID.execute-api.ap-south-1.amazonaws.com/
# → 200 OK
```

**Fix**: One line in Lambda@Edge, before setting `request.origin`:

```javascript
request.headers['host'] = [{ key: 'Host', value: 'precache.myapp.com' }];
```

This is not documented prominently in AWS guides but is a known gotcha with Lambda@Edge + API Gateway custom domains.

---

## Scale Analysis and Cost Comparison

### Renders vs Requests — The Critical Distinction

**prerender.io** charges per **render** — a render happens only when their headless Chrome actually runs (cache miss on their end). Repeated requests for the same URL within the cache window don't cost extra renders.

**Our system** works the same way:
- **Cache miss** = Puppeteer runs → slow (~8s), costs compute
- **Cache hit** = S3 returns cached HTML → fast (~300ms), costs almost nothing

### Our Cache Is Bounded by Content, Not Traffic

With 241 content pages and a 24-hour TTL:

```
Maximum renders per month = 241 pages × 30 days = 7,230

No matter how many millions of requests arrive,
Puppeteer runs at most 7,230 times per month.
```

At 1,000,000 bot requests per month with a 99.3% cache hit rate, we still only render 7,230 times. This is the structural advantage of URL-level S3 caching.

### AWS Pricing Used (ap-south-1)

| Service | Pricing |
|---|---|
| Lambda invocations | First 1M/month free, then $0.20/1M |
| Lambda compute | First 400,000 GB-s/month free, then $0.0000167/GB-s |
| Lambda memory | 2048MB = 2GB |
| Cache miss compute | 2GB × 8s = 16 GB-s per render |
| Cache hit compute | 2GB × 0.5s = 1 GB-s per request |
| API Gateway HTTP API | $1.00 per million requests |
| S3 GET | $0.00043 per 1,000 requests |
| S3 PUT | $0.0054 per 1,000 requests |
| Data transfer out | First 100GB/month free |

### Cost Comparison at Scale

| Bot Requests/mo | Renders (cache miss) | Cache Hits | Lambda Compute | API Gateway | **Our Cost** | **prerender.io $49** |
|---|---|---|---|---|---|---|
| ~100 (today) | ~20 | ~80 | 400 GB-s ✓ free | $0.00 | **$0** | $49 |
| 1,000 | ~200 | ~800 | 4,000 GB-s ✓ free | $0.001 | **~$0** | $49 |
| 10,000 | ~1,000 | ~9,000 | 25,000 GB-s ✓ free | $0.01 | **~$0.01** | $49 |
| 100,000 | ~3,000 | ~97,000 | 145,000 GB-s ✓ free | $0.10 | **~$0.10** | $49 |
| 1,000,000 | ~7,230 | ~992,770 | 1.1M GB-s → $11.81 | $1.00 | **~$13** | $199+ |
| 5,000,000 | ~7,230 | ~4,992,770 | 5.1M GB-s → $78 | $5.00 | **~$99** | Enterprise |

> prerender.io $49 plan includes 25,000 renders/month. Extra renders cost $2 per 1,000. Our system never exceeds 7,230 renders/month (bounded by content count), so we'd never hit their overage pricing either.

### In INR (₹83 = $1 approx)

```
Today        → ₹0       vs ₹5,000/month   → saves ₹5,000/month
1K req/mo    → ₹0       vs ₹5,000/month   → saves ₹5,000/month
10K req/mo   → ₹1       vs ₹5,000/month   → saves ₹4,999/month
100K req/mo  → ₹10      vs ₹5,000/month   → saves ₹4,990/month
1M req/mo    → ₹1,100   vs ₹16,000+/month → saves ₹14,900+/month
5M req/mo    → ₹8,300   vs Enterprise      → saves significantly
```

### When Does prerender.io Win?

At extreme scale (10M+ requests/month) and where **geographic rendering** matters — prerender.io has global PoPs, so renders happen near the requesting bot. Our renderer is in `ap-south-1`. For an Indian platform with Indian bots, this is fine. For a global platform, you'd want renderers in multiple regions.

### Future Optimization: CloudFront-Level Caching

Currently every bot request invokes our Lambda (even cache hits, just for 0.5s). At 1M+ requests/month this adds up. The fix: enable **CloudFront caching** on the `/prerender/*` behavior with a 24-hour TTL.

```
First bot request for /article/xyz in 24h
    → Lambda invoked → Puppeteer renders → CloudFront caches response

Next 999 bot requests for same URL in same 24h window
    → CloudFront edge serves directly → Lambda never invoked
    → Cost: $0
```

This collapses 1M Lambda invocations to ~7,230 per month. At that point the 1M/month scenario costs under $1 instead of $13. Worth implementing when you approach that scale.

---

## Infrastructure as Code

All infrastructure is defined in CloudFormation. One command deploys everything: S3 bucket, IAM role, Lambda function, API Gateway, TLS certificate, custom domain, and Route 53 DNS record.

See `cloudformation/renderer.yaml`.

```bash
# 1. Build and push the Docker image first
cd renderer-lambda
docker build --platform linux/amd64 --provenance=false -t my-renderer:latest .
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com
docker tag my-renderer:latest \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/my-renderer:latest
docker push \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/my-renderer:latest

# 2. Deploy the stack
cd ..
aws cloudformation deploy \
  --template-file cloudformation/renderer.yaml \
  --stack-name my-prerender \
  --region ap-south-1 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ECRImageUri=YOUR_ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/my-renderer:latest \
      DomainName=precache.myapp.com \
      HostedZoneId=YOUR_HOSTED_ZONE_ID \
      InternalToken=$(openssl rand -hex 32) \
      SiteUrl=https://myapp.com

# 3. Update Lambda@Edge (us-east-1) manually — see socialbots function
# 4. Publish new Lambda@Edge version → update CloudFront behavior ARN
# 5. Cancel prerender.io
```

> **Note**: ECR repository must be created separately before the first deploy:
> ```bash
> aws ecr create-repository --repository-name my-renderer --region ap-south-1
> ```

---

## Trade-offs and Honest Assessment

### Advantages

**Pay-per-use with a hard ceiling**: Renders are bounded by content count. 241 pages × 30 days = 7,230 renders max regardless of traffic. Costs can't spiral.

**Full control**: Cache TTL, bot detection rules, Puppeteer behaviour — all tunable. With prerender.io, you accept their defaults.

**No vendor lock-in**: One day prerender.io could shut down, change pricing, or have an outage. This infrastructure is yours and runs indefinitely.

**Transparency**: CloudWatch logs show exactly which bots crawl which pages, render durations, cache hit ratios.

**Warm cache hits are fast**: ~300ms, comparable to prerender.io's cached responses.

### Honest Limitations

**Cold start on cache miss**: First bot request for a new URL takes 5–10 seconds. Lambda cold start + Chromium launch + Angular data fetching. Bots are patient, but it's not instant.

**You own the Chromium version**: If `@sparticuz/chromium` has a bug or Chrome updates break something, it's your problem. prerender.io handles this silently. Plan to update the package ~quarterly.

**Lambda@Edge timeout risk**: Lambda@Edge has a hard 30-second origin timeout. Complex pages that take longer than ~25 seconds to render will return a 504. Hasn't happened in practice, but it's a ceiling.

**No geographic rendering**: Our renderer Lambda is in `ap-south-1`. For a global platform, bots crawling from the US or Europe add ~150–200ms latency to the render. For an Indian platform with Indian bots, this doesn't matter.

**One-time engineering cost**: Setting up this system took a day of work and debugging. prerender.io takes 30 minutes. Factor this in if your time is expensive.

---

## What I'd Do Differently

**Skip Lambda Function URL entirely.** I spent time debugging why it returned 403 before discovering account-level Lambda Block Public Access. Go straight to API Gateway HTTP API.

**Set the Host header fix from the start.** The CloudFront + Lambda@Edge + API Gateway combination requires explicitly setting the Host header when dynamically changing origins. This isn't prominently documented and cost debugging time.

**Add cache warming on content publish.** When you publish a new article or post, proactively call the renderer so the first bot always gets a cache hit. A simple webhook from the publishing backend → direct HTTP call to your renderer endpoint → primes S3 cache.

**Use CloudFormation from day one.** We ended up writing the CloudFormation template after manually deploying. Starting with IaC saves time when you need to redeploy or modify.

---

## Final Results

```bash
# WhatsApp bot
HTTP 200 — 2.09s  (cache miss on first request — Puppeteer rendered)

# Googlebot (second request, cache hit)
HTTP 200 — 0.30s

# LinkedIn
HTTP 200 — 0.37s

# Regular user → Amplify, not renderer — no change
HTTP 200 — 0.18s
```

Rendered HTML for the article includes the correct title and meta tags:
```html
<title>My Article Title | My App</title>
<meta property="og:title" content="..." />
<meta property="og:description" content="..." />
<meta property="og:image" content="..." />
```

Link previews on WhatsApp, LinkedIn, and Twitter work correctly. Googlebot indexes full content. The ₹5,000/month prerender.io subscription is cancelled.

**Cost: ₹0/month today. ₹1,100/month at 1 million bot requests. ₹8,300/month at 5 million.**

---

## Repository Structure

```
prerender-replacement/
├── BLOG.md                        ← this post
├── lambda-edge.js                 ← updated socialbots Lambda@Edge function
├── renderer-lambda/
│   ├── index.js                   ← Puppeteer renderer + S3 cache
│   ├── package.json
│   └── Dockerfile
├── cloudformation/
│   └── renderer.yaml              ← full infrastructure as code
└── iam-policy.json                ← standalone IAM policy (if not using CloudFormation)
```

---

*Built on AWS: Lambda, API Gateway HTTP API, S3, CloudFront, Lambda@Edge, ACM, Route 53, ECR*
*Stack: Node.js 20, Puppeteer, @sparticuz/chromium, AWS SDK v3*
*Platform: Angular SPA on AWS Amplify*
