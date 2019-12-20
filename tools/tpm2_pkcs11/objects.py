# SPDX-License-Identifier: BSD-2-Clause
import binascii
import yaml

# local imports
from .utils import get_ec_params
from .utils import asn1_format_ec_point_uncompressed
from .utils import str2bytes

from .pkcs11t import *  # noqa

class PKCS11Object(dict):

    def __init__(self, objclass, attrs, auth=None, tpm_priv=None, tpm_pub=None):
        super(PKCS11Object, self).__init__()

        attrs[CKA_CLASS] = objclass

        if auth is not None and tpm_priv:
            # hexencode the ENC obj auth string because str are hex encoded
            attrs[CKA_TPM2_OBJAUTH_ENC] = binascii.hexlify(str2bytes(auth)).decode()

        #
        # the priv/pub tpm objects are paths to where they are stored, so
        # read them and convert to hex
        #
        privhex=None
        if tpm_priv is not None:
            with open(tpm_priv, "rb") as f:
                privhex = binascii.hexlify(f.read()).decode()

        pubhex=None
        if tpm_pub is not None:
            with open(tpm_pub, "rb") as f:
                pubhex = binascii.hexlify(f.read()).decode()

        if pubhex is not None:
            attrs[CKA_TPM2_PUB_BLOB] = pubhex

        if privhex is not None:
            attrs[CKA_TPM2_PRIV_BLOB] = privhex

        self.update(attrs)


    def genmechs(self, tpm2):
        raise NotImplementedError()

class PKCS11StorageObject(PKCS11Object):

    def __init__(self, objclass, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        defpriv = objclass in [CKO_PRIVATE_KEY, CKO_SECRET_KEY]

        add = {
            CKA_TOKEN: True,
            CKA_PRIVATE: attrs[CKA_PRIVATE] if CKA_PRIVATE in attrs else defpriv,
            CKA_MODIFIABLE: False,
            CKA_LABEL: attrs[CKA_LABEL] if CKA_LABEL in attrs else '',
            CKA_COPYABLE: False,
            CKA_DESTROYABLE: True
        }

        attrs.update(add)

        super(PKCS11StorageObject, self).__init__(objclass, attrs, auth, tpm_priv, tpm_pub)

class PKCS11CertificateObject(PKCS11StorageObject):

    def __init__(self, objtype, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_CERTIFICATE_TYPE: objtype,
            CKA_TRUSTED : False,
            CKA_CERTIFICATE_CATEGORY: attrs[CKA_CERTIFICATE_CATEGORY] if CKA_CERTIFICATE_CATEGORY in attrs else CK_CERTIFICATE_CATEGORY_UNSPECIFIED,
            CKA_CHECK_VALUE: attrs[CKA_CHECK_VALUE]
        }

        attrs.update(add)

        super(PKCS11CertificateObject, self).__init__(CKO_CERTIFICATE, attrs, auth, tpm_priv, tpm_pub)

class PKCS11X509(PKCS11CertificateObject):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):
        super(PKCS11X509, self).__init__(CKC_X_509, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm2):
        # X509 objects do not have mechanisms
        pass

class PKCS11Key(PKCS11StorageObject):

    def __init__(self, objclass, objtype, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            # type of key
            CKA_KEY_TYPE : objtype,
            # Key identifier for key (default empty)
            CKA_ID : attrs[CKA_ID] if CKA_ID in attrs else '',
            # Start date for the key (default empty)
            CKA_START_DATE: attrs[CKA_START_DATE] if CKA_START_DATE in attrs else '',
            # End date for the key (default empty)
            CKA_END_DATE: attrs[CKA_END_DATE] if CKA_END_DATE in attrs else '',
            # CK_TRUE if generated in TPM else FALSE
            CKA_LOCAL: attrs[CKA_LOCAL],
            # The mechanism used to generate the key
            CKA_KEY_GEN_MECHANISM: attrs[CKA_KEY_GEN_MECHANISM],
            # A list of mechanisms allowed to be used with this key
            # no default listed, but for now just make empty
            # this is later updated by gen_mech
            CKA_ALLOWED_MECHANISMS: attrs[CKA_ALLOWED_MECHANISMS] if CKA_ALLOWED_MECHANISMS in attrs else '',
            CKA_DERIVE: attrs[CKA_DERIVE] if CKA_DERIVE in attrs else False
        }

        attrs.update(add)

        super(PKCS11Key, self).__init__(objclass, attrs, auth, tpm_priv, tpm_pub)


class PKCS11PublicKey(PKCS11Key):

    def __init__(self, objtype, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_SUBJECT: attrs[CKA_SUBJECT] if CKA_SUBJECT in attrs else '',
            CKA_ENCRYPT: attrs[CKA_ENCRYPT],
            CKA_VERIFY: attrs[CKA_VERIFY],
            CKA_VERIFY_RECOVER: False,
            CKA_WRAP: False,
            CKA_TRUSTED: False,
            CKA_WRAP_TEMPLATE: attrs[CKA_WRAP_TEMPLATE] if CKA_WRAP_TEMPLATE in attrs else '',
            # TODO generate
            CKA_PUBLIC_KEY_INFO: ''
        }

        attrs.update(add)

        super(PKCS11PublicKey, self).__init__(CKO_PUBLIC_KEY, objtype, attrs, auth, tpm_priv, tpm_pub)

class PKCS11RSAPublicKey(PKCS11PublicKey):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_MODULUS_BITS: attrs[CKA_MODULUS_BITS],
        }

        attrs.update(add)

        super(PKCS11RSAPublicKey, self).__init__(CKK_RSA, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm):
        capdata = tpm.getcap('algorithms')
        y = yaml.safe_load(capdata)

        # TPM's always support these
        pubmech = [
            CKM_RSA_X_509,
            CKM_RSA_PKCS_OAEP,
            CKM_RSA_PKCS,
            CKM_SHA256_RSA_PKCS
        ]

        if 'rsapss' in y:
            pubmech.append(CKM_RSA_PKCS_PSS)

        self.update({CKA_ALLOWED_MECHANISMS: pubmech})

class PKCS11ECPublicKey(PKCS11PublicKey):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_EC_POINT: attrs[CKA_EC_POINT],
            CKA_EC_PARAMS: attrs[CKA_EC_PARAMS],
        }

        attrs.update(add)

        super(PKCS11ECPublicKey, self).__init__(CKK_EC, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm):
        pubmech = [ CKM_ECDSA, CKM_ECDSA_SHA1 ]
        self.update({CKA_ALLOWED_MECHANISMS: pubmech})

class PKCS11PrivateKey(PKCS11Key):

    def __init__(self, objtype, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_SENSITIVE: True,
            CKA_SUBJECT: attrs[CKA_SUBJECT] if CKA_SUBJECT in attrs else '',
            CKA_DECRYPT: attrs[CKA_DECRYPT],
            CKA_SIGN: attrs[CKA_SIGN],
            CKA_SIGN_RECOVER: False,
            CKA_UNWRAP: False,
            CKA_EXTRACTABLE: attrs[CKA_EXTRACTABLE],
            CKA_ALWAYS_SENSITIVE: attrs[CKA_ALWAYS_SENSITIVE],
            CKA_NEVER_EXTRACTABLE: attrs[CKA_NEVER_EXTRACTABLE],
            CKA_WRAP_WITH_TRUSTED: False,
            CKA_UNWRAP_TEMPLATE: attrs[CKA_UNWRAP_TEMPLATE] if CKA_UNWRAP_TEMPLATE in attrs else [],
            CKA_ALWAYS_AUTHENTICATE: attrs[CKA_ALWAYS_AUTHENTICATE] if CKA_ALWAYS_AUTHENTICATE in attrs else False,
            CKA_PUBLIC_KEY_INFO: ''
        }

        attrs.update(add)

        super(PKCS11PrivateKey, self).__init__(CKO_PRIVATE_KEY, objtype, attrs, auth, tpm_priv, tpm_pub)

class PKCS11RSAPrivateKey(PKCS11PrivateKey):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_MODULUS: attrs[CKA_MODULUS],
            CKA_PUBLIC_EXPONENT: attrs [CKA_PUBLIC_EXPONENT],
        }

        attrs.update(add)

        super(PKCS11RSAPrivateKey, self).__init__(CKK_RSA, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm):
        capdata = tpm.getcap('algorithms')
        y = yaml.safe_load(capdata)

        # TPM's always support these
        privmech = [
            CKM_RSA_X_509,
            CKM_RSA_PKCS_OAEP,
            CKM_RSA_PKCS,
            CKM_SHA1_RSA_PKCS,
            CKM_SHA256_RSA_PKCS,
            CKM_SHA384_RSA_PKCS,
            CKM_SHA512_RSA_PKCS,
            CKM_SHA256_RSA_PKCS
        ]

        if 'rsapss' in y:
            privmech.append(CKM_RSA_PKCS_PSS)

        self.update({CKA_ALLOWED_MECHANISMS: privmech})

class PKCS11ECPrivateKey(PKCS11PrivateKey):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_EC_POINT: attrs[CKA_EC_POINT],
            CKA_EC_PARAMS: attrs[CKA_EC_PARAMS],
        }

        attrs.update(add)

        super(PKCS11ECPrivateKey, self).__init__(CKK_EC, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm):
        privmech = [ CKM_ECDSA, CKM_ECDSA_SHA1 ]
        self.update({CKA_ALLOWED_MECHANISMS: privmech})

class PKCS11SecretKey(PKCS11Key):

    def __init__(self, objtype, attrs, auth=None, tpm_priv=None, tpm_pub=None):

        add = {
            CKA_SENSITIVE: True,
            CKA_ENCRYPT: attrs[CKA_ENCRYPT],
            CKA_DECRYPT: attrs[CKA_DECRYPT],
            CKA_SIGN: attrs[CKA_SIGN] if CKA_SIGN in attrs else attrs[CKA_ENCRYPT],
            CKA_VERIFY: attrs[CKA_DECRYPT] if CKA_DECRYPT in attrs else attrs[CKA_DECRYPT],
            CKA_WRAP: False,
            CKA_UNWRAP: False,
            CKA_EXTRACTABLE: attrs[CKA_EXTRACTABLE],
            CKA_ALWAYS_SENSITIVE: attrs[CKA_ALWAYS_SENSITIVE],
            CKA_NEVER_EXTRACTABLE: attrs[CKA_NEVER_EXTRACTABLE],
            # TODO Skipping CKA_CHECKVALUE
            CKA_WRAP_WITH_TRUSTED: False,
            CKA_TRUSTED: False,
            CKA_WRAP_TEMPLATE: attrs[CKA_WRAP_TEMPLATE] if CKA_WRAP_TEMPLATE in attrs else [],
            CKA_UNWRAP_TEMPLATE: '',
            # placate pkcs11 tool
            CKA_VALUE: '',
            CKA_VALUE_LEN: attrs[CKA_VALUE_LEN],
        }

        attrs.update(add)

        super(PKCS11SecretKey, self).__init__(CKO_SECRET_KEY, objtype, attrs, auth, tpm_priv, tpm_pub)

class PKCS11AESKey(PKCS11SecretKey):

    def __init__(self, attrs, auth=None, tpm_priv=None, tpm_pub=None):
        super(PKCS11AESKey, self).__init__(CKK_AES, attrs, auth, tpm_priv, tpm_pub)

    def genmechs(self, tpm):
        mechs = [
            CKM_AES_CBC
        ]
        self.update({CKA_ALLOWED_MECHANISMS: mechs})

def PKCS11ObjectFactory(public_yaml_data, tpm, auth, init_pubattrs, init_privattrs, tpm_pub, tpm_priv):

    objtype = public_yaml_data['type']['value']
    tpmattrs=public_yaml_data['attributes']['value'].split('|')

    # if we need to support non-null schemes we need to map tpm2 alg to pkcs11 alg
    # and populate CKA_ALLOWED_MECHANISMS and skip calling genmechs()
    scheme = public_yaml_data['scheme']['value'] if 'scheme' in public_yaml_data else None
    if scheme != None:
        raise RuntimeError('Cannot map scheme to allowed mechanism, got: "{}"'.format(scheme))

    pubkey=None
    privkey=None

    pubattrs = init_pubattrs if init_pubattrs else {}
    privattrs = init_privattrs if init_pubattrs else {}

    if objtype == 'rsa':

        exp = public_yaml_data['exponent'] if int(public_yaml_data['exponent']) != 0 else 65537
        exp = '{0:X}'.format(exp)
        # if it's odd in len, pad it with a leading zero
        if len(exp) % 2:
            exp = '0{}'.format(exp)
        pubattrs[CKA_MODULUS] = public_yaml_data['rsa']
        pubattrs[CKA_MODULUS_BITS] = public_yaml_data['bits']
        pubattrs[CKA_PUBLIC_EXPONENT] = exp

        pubattrs[CKA_ENCRYPT] = 'sign' in tpmattrs
        pubattrs[CKA_VERIFY] = 'decrypt' in tpmattrs
        pubattrs[CKA_LOCAL] = 'sensitivedataorigin' in tpmattrs

        pubattrs[CKA_KEY_GEN_MECHANISM] = CKM_RSA_PKCS_KEY_PAIR_GEN

        privattrs[CKA_MODULUS] = pubattrs[CKA_MODULUS]
        privattrs[CKA_MODULUS_BITS] = pubattrs[CKA_MODULUS_BITS]
        privattrs[CKA_PUBLIC_EXPONENT] = pubattrs[CKA_PUBLIC_EXPONENT]
        privattrs[CKA_LOCAL] = pubattrs[CKA_LOCAL]

        privattrs[CKA_DECRYPT] = 'decrypt' in tpmattrs
        privattrs[CKA_SIGN] = 'sign' in tpmattrs
        privattrs[CKA_EXTRACTABLE] = not ('fixedtpm' in tpmattrs and 'fixedparent' in tpmattrs)
        privattrs[CKA_ALWAYS_SENSITIVE] = not privattrs[CKA_EXTRACTABLE]
        privattrs[CKA_NEVER_EXTRACTABLE] = not privattrs[CKA_EXTRACTABLE]

        privattrs[CKA_KEY_GEN_MECHANISM] = CKM_RSA_PKCS_KEY_PAIR_GEN

        pubkey = PKCS11RSAPublicKey(pubattrs, auth, tpm_pub=tpm_pub)
        privkey = PKCS11RSAPrivateKey(privattrs, auth, tpm_pub=tpm_pub, tpm_priv=tpm_priv)

    elif objtype == 'ecc':

        curveid = public_yaml_data['curve-id']['value']
        ecparams = get_ec_params(curveid)
        ecpoint = asn1_format_ec_point_uncompressed(public_yaml_data['x'], public_yaml_data['y'])
        pubattrs[CKA_EC_PARAMS] = ecparams
        pubattrs[CKA_EC_POINT] = ecpoint
        pubattrs[CKA_ENCRYPT] = 'sign' in tpmattrs
        pubattrs[CKA_VERIFY] = 'decrypt' in tpmattrs
        pubattrs[CKA_LOCAL] = 'sensitivedataorigin' in tpmattrs

        pubattrs[CKA_KEY_GEN_MECHANISM] = CKM_EC_KEY_PAIR_GEN

        privattrs[CKA_LOCAL] = pubattrs[CKA_LOCAL]

        privattrs[CKA_DECRYPT] = 'decrypt' in tpmattrs
        privattrs[CKA_SIGN] = 'sign' in tpmattrs
        privattrs[CKA_EXTRACTABLE] = not ('fixedtpm' in tpmattrs and 'fixedparent' in tpmattrs)
        privattrs[CKA_ALWAYS_SENSITIVE] = not privattrs[CKA_EXTRACTABLE]
        privattrs[CKA_NEVER_EXTRACTABLE] = not privattrs[CKA_EXTRACTABLE]
        privattrs[CKA_EC_PARAMS] = pubattrs[CKA_EC_PARAMS] = ecparams
        privattrs[CKA_EC_POINT] = pubattrs[CKA_EC_POINT] = ecpoint

        privattrs[CKA_KEY_GEN_MECHANISM] = CKM_EC_KEY_PAIR_GEN

        pubkey = PKCS11ECPublicKey(pubattrs, auth, tpm_pub=tpm_pub)
        privkey = PKCS11ECPrivateKey(privattrs, auth, tpm_pub=tpm_pub, tpm_priv=tpm_priv)

    elif objtype == 'symcipher':

        symalg = public_yaml_data['sym-alg']['value']

        if symalg != 'aes':
            raise RuntimeError('Cannot handle sym-alg: {}'.format(symalg))

        privattrs[CKA_VALUE_LEN] = public_yaml_data['sym-keybits'] // 8
        privattrs[CKA_KEY_GEN_MECHANISM] = CKM_AES_KEY_GEN
        privattrs[CKA_ENCRYPT] = 'sign' in tpmattrs
        privattrs[CKA_DECRYPT] = 'decrypt' in tpmattrs
        privattrs[CKA_EXTRACTABLE] = not ('fixedtpm' in tpmattrs and 'fixedparent' in tpmattrs)
        privattrs[CKA_LOCAL] = 'sensitivedataorigin' in tpmattrs
        privattrs[CKA_ALWAYS_SENSITIVE] = not privattrs[CKA_EXTRACTABLE]
        privattrs[CKA_NEVER_EXTRACTABLE] = not privattrs[CKA_EXTRACTABLE]

        privkey = PKCS11AESKey(privattrs, auth, tpm_pub=tpm_pub, tpm_priv=tpm_priv)

    else:
        raise RuntimeError("Cannot handle keytype: {}".format(public_yaml_data['type']))

    privkey.genmechs(tpm)
    if pubkey:
        pubkey.genmechs(tpm)

    return {'private' : privkey, 'public': pubkey }