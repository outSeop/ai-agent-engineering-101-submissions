"""Host-only address-serialized adapter for the unchanged official Signer.

No automatic installation, key loading, chain access, payment policy or durable
send journal. The one main Signer instance must remain shared by stock/refund.
Locks cover the original do(pay) call, including its receipt wait. Separate
processes are not coordinated; ambiguous broadcasts still require durable
pre-send intent and receipt/nonce recovery in the business tool.
"""
import re
from threading import Lock

_ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}\Z')
_REGISTRY_GUARD = Lock()
_ADDRESS_LOCKS = {}
_ADAPTER_MARKER = object()


def _lock_for_address(address):
    """One process-local lock per actual wallet address, independent of role."""
    if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
        raise ValueError('wallet has no valid address')
    normalized = address.lower()
    with _REGISTRY_GUARD:
        return _ADDRESS_LOCKS.setdefault(normalized, Lock())


def serialized_signer_class(official_signer):
    """Return a subclass; never mutate the SDK class or construct another signer.

    A future main launcher may select this class before its original cmd_run
    creates the shared signer. Role-to-wallet mappings must stay stable for the
    lifetime of that signer, as in the official launcher.
    """
    if getattr(official_signer, '_address_serialization_marker', None) is _ADAPTER_MARKER:
        return official_signer

    class AddressSerializedSigner(official_signer):
        _address_serialization_marker = _ADAPTER_MARKER
        def do(self, request):
            if request.get('op') != 'pay':
                return super().do(request)
            # Freeze caller-owned primitive pay fields while a request waits.
            # No capability/limit/role decision is cached outside the lock.
            payment_request = dict(request)
            try:
                wallet = self.keys.get(payment_request.get('role'))
            except TypeError:
                return super().do(payment_request)
            if wallet is None:
                # This path cannot pay; preserve the original denial semantics.
                return super().do(payment_request)
            with _lock_for_address(wallet.address):
                # Authorization is deliberately performed by the original SDK
                # only after acquiring the address lock. Waiting revoked or
                # expired capabilities must fail here, before maroo.pay.
                return super().do(payment_request)

    AddressSerializedSigner.__name__ = 'AddressSerializedSigner'
    return AddressSerializedSigner
