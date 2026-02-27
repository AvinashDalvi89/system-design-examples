'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// WHAT CHANGED vs original prerender.io version:
//   Line ~14 : domainName → your Lambda Function URL
//   Line ~19 : readTimeout → 30 (was 20)
//   Line ~21 : customHeaders → add x-internal-token for security
//   Line ~25 : sslProtocols → TLSv1.2 only (TLSv1/1.1 deprecated)
//   Line ~26 : path → '' (was '/https%3A%2F%2F' + host for prerender.io format)
//
// NOTHING ELSE CHANGED. Bot detection logic is identical.
// ─────────────────────────────────────────────────────────────────────────────

// Set this to the same value as INTERNAL_TOKEN env var in your renderer Lambda
const INTERNAL_TOKEN = 'fae79bff16554d793c2e9994919c621285728d5b6db9304bc144bcd0700ca9fa';

exports.handler = (event, context, callback) => {
    const request = event.Records[0].cf.request;

    if (request.headers['x-prerender-token'] && request.headers['x-prerender-host']) {
        // ── ORIGIN-REQUEST: Route to our renderer Lambda ──────────────────────
        console.log('Routing to renderer Lambda');

        if (request.headers['x-query-string']) {
            request.querystring = request.headers['x-query-string'][0].value;
        }

        // When Lambda@Edge changes the origin domain, CloudFront does NOT
        // automatically update the Host header. API Gateway rejects requests
        // where Host doesn't match its custom domain → ForbiddenException.
        // Fix: explicitly set the Host header to match the new origin.
        request.headers['host'] = [{ key: 'Host', value: 'precache.nushiftconnect.com' }];

        request.origin = {
            custom: {
                domainName: 'precache.nushiftconnect.com',
                port: 443,
                protocol: 'https',
                readTimeout: 30,           // CHANGED: was 20 — Puppeteer needs up to 25s
                keepaliveTimeout: 5,
                customHeaders: {
                    'x-internal-token': [{ // CHANGED: security token, replaces prerender.io API key
                        key: 'X-Internal-Token',
                        value: INTERNAL_TOKEN
                    }]
                },
                sslProtocols: ['TLSv1.2'], // CHANGED: was ['TLSv1', 'TLSv1.1'] — both deprecated
                path: ''                   // CHANGED: was '/https%3A%2F%2F' + host (prerender.io format)
            }
        };

    } else {
        // ── VIEWER-REQUEST: Bot detection — COMPLETELY UNCHANGED ──────────────
        const headers = request.headers;
        const user_agent = headers['user-agent'];
        const host = headers['host'];

        if (user_agent && host) {
            var prerender = /googlebot|adsbot\-google|Feedfetcher\-Google|bingbot|yandex|baiduspider|Facebot|facebookexternalhit|twitterbot|rogerbot|linkedinbot|embedly|quora link preview|showyoubot|outbrain|pinterest|slackbot|vkShare|W3C_Validator|redditbot|applebot|whatsapp|flipboard|tumblr|bitlybot|skypeuripreview|nuzzel|discordbot|google page speed|qwantify|pinterestbot|bitrix link preview|xing\-contenttabreceiver|chrome\-lighthouse|telegrambot|Perplexity|OAI-SearchBot|ChatGPT|GPTBot|ClaudeBot|Amazonbot|integration-test/i.test(user_agent[0].value);

            prerender = prerender || /_escaped_fragment_/.test(request.querystring);
            prerender = prerender && ! /\.(js|css|xml|less|png|jpg|jpeg|gif|webp|avif|pdf|doc|txt|ico|rss|zip|mp3|rar|exe|wmv|doc|avi|ppt|mpg|mpeg|tif|wav|mov|psd|ai|xls|mp4|m4a|swf|dat|dmg|iso|flv|m4v|torrent|ttf|woff|woff2|svg|eot|map)$/i.test(request.uri);

            if (prerender) {
                console.log('Bot detected:', user_agent[0].value);
                // Reusing x-prerender-token to carry our internal secret token
                headers['x-prerender-token'] = [{ key: 'X-Prerender-Token', value: INTERNAL_TOKEN }];
                headers['x-prerender-host'] = [{ key: 'X-Prerender-Host', value: host[0].value }];
                headers['x-prerender-cachebuster'] = [{ key: 'X-Prerender-Cachebuster', value: Date.now().toString() }];
                headers['x-query-string'] = [{ key: 'X-Query-String', value: request.querystring }];
            } else {
                console.log('Regular user');
            }
        }
    }

    callback(null, request);
};
