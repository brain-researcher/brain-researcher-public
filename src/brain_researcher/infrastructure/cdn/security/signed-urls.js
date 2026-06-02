/**
 * Signed URLs and Token-based Security for Brain Researcher CDN
 * Implements secure access to protected resources with time-based expiration
 */

const crypto = require('crypto');
const jwt = require('jsonwebtoken');

class SignedURLManager {
    constructor(options = {}) {
        this.secretKey = options.secretKey || process.env.CDN_SECRET_KEY || this.generateSecret();
        this.jwtSecret = options.jwtSecret || process.env.JWT_SECRET || this.secretKey;
        this.defaultExpiry = options.defaultExpiry || 3600; // 1 hour
        this.clockSkew = options.clockSkew || 300; // 5 minutes
        this.algorithm = options.algorithm || 'HS256';

        // CloudFront configuration
        this.cloudfront = {
            keyPairId: options.cloudfrontKeyPairId || process.env.CLOUDFRONT_KEY_PAIR_ID,
            privateKey: options.cloudfrontPrivateKey || process.env.CLOUDFRONT_PRIVATE_KEY,
            distributionDomain: options.distributionDomain || process.env.CLOUDFRONT_DOMAIN
        };
    }

    /**
     * Generate a secure secret key
     */
    generateSecret() {
        return crypto.randomBytes(32).toString('hex');
    }

    /**
     * Create HMAC signature for URL
     */
    createSignature(data, secret = null) {
        const key = secret || this.secretKey;
        return crypto
            .createHmac('sha256', key)
            .update(data)
            .digest('hex');
    }

    /**
     * Generate signed URL for protected resource
     */
    generateSignedURL(resourcePath, options = {}) {
        const {
            expiresIn = this.defaultExpiry,
            userId = null,
            permissions = ['read'],
            ipAddress = null,
            userAgent = null,
            maxDownloads = null
        } = options;

        const timestamp = Math.floor(Date.now() / 1000);
        const expires = timestamp + expiresIn;

        // Create payload
        const payload = {
            path: resourcePath,
            exp: expires,
            iat: timestamp,
            ...(userId && { sub: userId }),
            ...(permissions && { perms: permissions }),
            ...(ipAddress && { ip: ipAddress }),
            ...(userAgent && { ua: crypto.createHash('md5').update(userAgent).digest('hex') }),
            ...(maxDownloads && { maxDl: maxDownloads })
        };

        // Create signature
        const dataToSign = JSON.stringify(payload);
        const signature = this.createSignature(dataToSign);

        // Build query parameters
        const params = new URLSearchParams({
            expires: expires.toString(),
            signature,
            ...(userId && { uid: userId }),
            ...(permissions.length > 1 && { perms: permissions.join(',') })
        });

        // Return signed URL
        const separator = resourcePath.includes('?') ? '&' : '?';
        return `${resourcePath}${separator}${params.toString()}`;
    }

    /**
     * Generate JWT-based signed URL
     */
    generateJWTSignedURL(resourcePath, options = {}) {
        const {
            expiresIn = this.defaultExpiry,
            userId = null,
            permissions = ['read'],
            audience = 'brain-researcher-cdn'
        } = options;

        const payload = {
            path: resourcePath,
            sub: userId,
            aud: audience,
            perms: permissions,
            iat: Math.floor(Date.now() / 1000)
        };

        const token = jwt.sign(payload, this.jwtSecret, {
            expiresIn,
            algorithm: this.algorithm,
            issuer: 'brain-researcher'
        });

        const params = new URLSearchParams({ token });
        const separator = resourcePath.includes('?') ? '&' : '?';

        return `${resourcePath}${separator}${params.toString()}`;
    }

    /**
     * Generate CloudFront signed URL
     */
    generateCloudFrontSignedURL(resourcePath, options = {}) {
        if (!this.cloudfront.keyPairId || !this.cloudfront.privateKey) {
            throw new Error('CloudFront key pair ID and private key are required');
        }

        const {
            expiresIn = this.defaultExpiry,
            ipAddress = null,
            dateGreaterThan = null
        } = options;

        const expires = Math.floor(Date.now() / 1000) + expiresIn;
        const fullUrl = `https://${this.cloudfront.distributionDomain}${resourcePath}`;

        // Create policy
        const policy = {
            Statement: [
                {
                    Resource: fullUrl,
                    Condition: {
                        DateLessThan: {
                            'AWS:EpochTime': expires
                        },
                        ...(dateGreaterThan && {
                            DateGreaterThan: {
                                'AWS:EpochTime': dateGreaterThan
                            }
                        }),
                        ...(ipAddress && {
                            IpAddress: {
                                'AWS:SourceIp': ipAddress
                            }
                        })
                    }
                }
            ]
        };

        const policyString = JSON.stringify(policy);
        const policyBase64 = Buffer.from(policyString).toString('base64')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');

        // Create signature
        const sign = crypto.createSign('SHA1');
        sign.update(policyString);
        const signature = sign.sign(this.cloudfront.privateKey, 'base64')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');

        // Build signed URL
        const params = new URLSearchParams({
            'Key-Pair-Id': this.cloudfront.keyPairId,
            'Policy': policyBase64,
            'Signature': signature
        });

        const separator = fullUrl.includes('?') ? '&' : '?';
        return `${fullUrl}${separator}${params.toString()}`;
    }

    /**
     * Validate signed URL
     */
    validateSignedURL(url, options = {}) {
        try {
            const urlObj = new URL(url);
            const params = urlObj.searchParams;

            const expires = parseInt(params.get('expires'));
            const signature = params.get('signature');
            const userId = params.get('uid');
            const permissions = params.get('perms')?.split(',') || ['read'];

            if (!expires || !signature) {
                return { valid: false, error: 'Missing required parameters' };
            }

            // Check expiration
            const now = Math.floor(Date.now() / 1000);
            if (now > expires + this.clockSkew) {
                return { valid: false, error: 'URL has expired' };
            }

            if (now < expires - 86400 * 7) { // Not valid more than 7 days in future
                return { valid: false, error: 'URL not yet valid' };
            }

            // Reconstruct payload for signature validation
            const resourcePath = urlObj.pathname + (urlObj.search ? urlObj.search.replace(/[&?](expires|signature|uid|perms)=[^&]*/g, '') : '');
            const payload = {
                path: resourcePath,
                exp: expires,
                ...(userId && { sub: userId }),
                perms: permissions
            };

            const dataToSign = JSON.stringify(payload);
            const expectedSignature = this.createSignature(dataToSign);

            if (signature !== expectedSignature) {
                return { valid: false, error: 'Invalid signature' };
            }

            // Validate IP address if specified
            if (options.ipAddress && options.validateIP) {
                // Implementation depends on how IP was included in original signature
            }

            return {
                valid: true,
                payload: {
                    path: payload.path,
                    userId,
                    permissions,
                    expiresAt: new Date(expires * 1000)
                }
            };

        } catch (error) {
            return { valid: false, error: error.message };
        }
    }

    /**
     * Validate JWT signed URL
     */
    validateJWTSignedURL(url, options = {}) {
        try {
            const urlObj = new URL(url);
            const token = urlObj.searchParams.get('token');

            if (!token) {
                return { valid: false, error: 'Missing JWT token' };
            }

            const decoded = jwt.verify(token, this.jwtSecret, {
                algorithms: [this.algorithm],
                issuer: 'brain-researcher',
                audience: options.audience || 'brain-researcher-cdn',
                clockTolerance: this.clockSkew
            });

            return {
                valid: true,
                payload: {
                    path: decoded.path,
                    userId: decoded.sub,
                    permissions: decoded.perms || ['read'],
                    expiresAt: new Date(decoded.exp * 1000)
                }
            };

        } catch (error) {
            return {
                valid: false,
                error: error.name === 'TokenExpiredError' ? 'Token has expired' : error.message
            };
        }
    }

    /**
     * Generate access token for API authentication
     */
    generateAccessToken(userId, permissions = [], options = {}) {
        const {
            expiresIn = 3600,
            audience = 'brain-researcher-api',
            scope = 'api:read'
        } = options;

        const payload = {
            sub: userId,
            aud: audience,
            scope,
            perms: permissions,
            iat: Math.floor(Date.now() / 1000)
        };

        return jwt.sign(payload, this.jwtSecret, {
            expiresIn,
            algorithm: this.algorithm,
            issuer: 'brain-researcher'
        });
    }

    /**
     * Generate refresh token
     */
    generateRefreshToken(userId, options = {}) {
        const {
            expiresIn = 86400 * 30, // 30 days
            tokenFamily = crypto.randomBytes(16).toString('hex')
        } = options;

        const payload = {
            sub: userId,
            type: 'refresh',
            family: tokenFamily,
            iat: Math.floor(Date.now() / 1000)
        };

        return jwt.sign(payload, this.jwtSecret, {
            expiresIn,
            algorithm: this.algorithm,
            issuer: 'brain-researcher'
        });
    }

    /**
     * Generate pre-signed upload URL
     */
    generateUploadURL(fileName, options = {}) {
        const {
            expiresIn = 900, // 15 minutes
            maxFileSize = 10 * 1024 * 1024, // 10MB
            allowedMimeTypes = ['image/jpeg', 'image/png', 'image/webp'],
            userId = null
        } = options;

        const uploadId = crypto.randomUUID();
        const expires = Math.floor(Date.now() / 1000) + expiresIn;

        const payload = {
            uploadId,
            fileName,
            maxFileSize,
            allowedMimeTypes,
            expires,
            ...(userId && { userId })
        };

        const signature = this.createSignature(JSON.stringify(payload));

        return {
            uploadId,
            url: `/api/upload/${uploadId}?signature=${signature}&expires=${expires}`,
            expires: new Date(expires * 1000),
            constraints: {
                maxFileSize,
                allowedMimeTypes
            }
        };
    }

    /**
     * Express middleware for validating signed requests
     */
    validateSignedRequest(options = {}) {
        const { paramName = 'signature', pathParam = 'path' } = options;

        return (req, res, next) => {
            const signature = req.query[paramName] || req.headers['x-signature'];
            const path = req.params[pathParam] || req.path;

            if (!signature) {
                return res.status(401).json({ error: 'Missing signature' });
            }

            const validation = this.validateSignedURL(req.originalUrl, {
                ipAddress: req.ip,
                validateIP: options.validateIP
            });

            if (!validation.valid) {
                return res.status(401).json({ error: validation.error });
            }

            req.signedRequest = validation.payload;
            next();
        };
    }

    /**
     * Revoke signed URL (requires external storage)
     */
    async revokeSignedURL(url, reason = 'manual_revoke') {
        // Extract signature from URL for revocation list
        const urlObj = new URL(url);
        const signature = urlObj.searchParams.get('signature');

        if (!signature) {
            throw new Error('Invalid URL format');
        }

        // Store in revocation list (implement based on your storage)
        const revocation = {
            signature,
            url,
            reason,
            revokedAt: new Date(),
            expiresAt: new Date(Date.now() + 86400 * 1000) // Keep revocation for 24 hours
        };

        // await storeRevocation(revocation);

        return revocation;
    }

    /**
     * Batch generate signed URLs
     */
    generateBatchSignedURLs(resources, options = {}) {
        return resources.map(resource => ({
            resource,
            signedUrl: this.generateSignedURL(resource, options),
            expiresAt: new Date(Date.now() + (options.expiresIn || this.defaultExpiry) * 1000)
        }));
    }
}

module.exports = { SignedURLManager };

// Example usage and CLI
if (require.main === module) {
    const manager = new SignedURLManager();

    const command = process.argv[2];
    const resource = process.argv[3];

    switch (command) {
        case 'sign':
            if (!resource) {
                console.error('Please provide resource path');
                process.exit(1);
            }

            const signedUrl = manager.generateSignedURL(resource, {
                expiresIn: 3600,
                permissions: ['read']
            });

            console.log('Signed URL:', signedUrl);
            break;

        case 'validate':
            if (!resource) {
                console.error('Please provide URL to validate');
                process.exit(1);
            }

            const validation = manager.validateSignedURL(resource);
            console.log('Validation result:', validation);
            break;

        case 'jwt':
            if (!resource) {
                console.error('Please provide resource path');
                process.exit(1);
            }

            const jwtUrl = manager.generateJWTSignedURL(resource, {
                userId: 'test-user',
                permissions: ['read', 'download']
            });

            console.log('JWT Signed URL:', jwtUrl);
            break;

        default:
            console.log(`
Usage: node signed-urls.js <command> <resource>

Commands:
  sign <path>     Generate signed URL for resource
  validate <url>  Validate signed URL
  jwt <path>      Generate JWT signed URL

Examples:
  node signed-urls.js sign /api/data/dataset1.json
  node signed-urls.js validate "https://example.com/api/data?expires=123&signature=abc"
  node signed-urls.js jwt /api/protected/resource.pdf
            `);
    }
}