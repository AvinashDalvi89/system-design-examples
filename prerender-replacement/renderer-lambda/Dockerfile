# AWS Lambda Node.js 20 base image (Amazon Linux 2023)
# @sparticuz/chromium v133+ is compatible with AL2023
FROM public.ecr.aws/lambda/nodejs:20

# Copy dependency manifest first (layer caching — only re-runs npm install if
# package.json changes, not every code change)
COPY package.json ./

RUN npm install --omit=dev

# Copy function code
COPY index.js ./

# Lambda handler entrypoint
CMD ["index.handler"]
