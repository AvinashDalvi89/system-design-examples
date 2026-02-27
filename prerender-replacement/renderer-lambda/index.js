'use strict';

const chromium = require('@sparticuz/chromium');
const puppeteer = require('puppeteer-core');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const s3 = new S3Client({});

const BUCKET        = process.env.CACHE_BUCKET;
const CACHE_TTL_MS  = parseInt(process.env.CACHE_TTL_HOURS || '24') * 3600 * 1000;
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN;

// Reuse browser across warm Lambda invocations (saves ~4s per request)
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

// Convert S3 URL path to a safe S3 key
// /posts/my-post-123  →  cache/posts/my-post-123.html
// /                   →  cache/index.html
function pathToS3Key(urlPath) {
    const clean = (urlPath.replace(/^\/+|\/+$/g, '') || 'index').replace(/\.html$/, '');
    return `cache/${clean}.html`;
}

// Returns true if the path looks like a real app route worth caching.
// Rejects paths that contain JS template literal syntax (${...}), string
// concatenation artifacts (+), or other characters that never appear in
// real URLs — these come from bots following un-evaluated code fragments.
// Also rejects static asset extensions which should never be prerendered.
function isValidPath(urlPath) {
    if (!/^[a-zA-Z0-9\-_\/\.~%]+$/.test(urlPath)) return false;
    if (/\.(js|css|png|jpg|jpeg|gif|webp|avif|svg|ico|woff|woff2|ttf|eot|mp4|mp3|pdf|map|xml|txt|zip)$/i.test(urlPath)) return false;
    return true;
}

exports.handler = async (event) => {
    const headers = event.headers || {};

    // ── Security: reject requests without the internal token ──────────────────
    if (INTERNAL_TOKEN) {
        const token = headers['x-internal-token'] || headers['x-prerender-token'];
        if (token !== INTERNAL_TOKEN) {
            console.log('Rejected: missing or wrong internal token');
            return { statusCode: 403, body: 'Forbidden' };
        }
    }

    const urlPath   = event.rawPath || '/';
    const host      = headers['x-prerender-host'] || 'nushiftconnect.com';
    const targetUrl = `https://${host}${urlPath}`;
    const s3Key     = pathToS3Key(urlPath);
    const cacheable = isValidPath(urlPath);

    if (!cacheable) {
        console.log(`Skipping cache for invalid path: ${urlPath}`);
    }

    // ── 1. Check S3 cache ─────────────────────────────────────────────────────
    if (cacheable) try {
        const cached = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: s3Key }));
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
        if (err.name !== 'NoSuchKey') {
            console.error('S3 read error:', err.message);
        }
        console.log(`CACHE MISS [${urlPath}]`);
    }

    // ── 2. Render with Puppeteer ──────────────────────────────────────────────
    console.log(`Rendering: ${targetUrl}`);

    let html;
    try {
        const b    = await getBrowser();
        const page = await b.newPage();

        // Block images / fonts / media — they don't affect HTML content
        // and blocking them cuts render time by 30-60%
        await page.setRequestInterception(true);
        page.on('request', (req) => {
            if (['image', 'font', 'media'].includes(req.resourceType())) {
                req.abort();
            } else {
                req.continue();
            }
        });

        // networkidle0 = wait until no network activity for 500ms
        // This is how prerender.io works — no Angular code changes needed
        await page.goto(targetUrl, {
            waitUntil: 'networkidle0',
            timeout: 25000,
        });

        html = await page.content();
        await page.close();

    } catch (err) {
        console.error(`Render failed [${targetUrl}]:`, err.message);
        // Reset browser on crash so next invocation gets a fresh one
        if (browser) {
            try { await browser.close(); } catch (_) {}
            browser = null;
        }
        return {
            statusCode: 500,
            headers: { 'content-type': 'text/plain' },
            body: 'Render error — try again shortly',
        };
    }

    // ── 3. Store in S3 cache ──────────────────────────────────────────────────
    if (cacheable) try {
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
        console.log(`Cached [${s3Key}]`);
    } catch (err) {
        // Cache write failure is non-fatal — bot still gets the HTML
        console.error('S3 write error:', err.message);
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
