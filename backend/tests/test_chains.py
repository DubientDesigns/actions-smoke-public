import pytest

from cit.chains import BY_SLUG, InvalidAddress, is_quote_asset, normalize_address


def test_evm_addresses_are_lowercased():
    assert normalize_address(BY_SLUG["bsc"], "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c") == (
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c")


def test_solana_addresses_keep_case():
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert normalize_address(BY_SLUG["solana"], mint) == mint


@pytest.mark.parametrize("chain,addr", [
    ("ethereum", "0x123"), ("ethereum", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    ("solana", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"), ("solana", "0OIl" * 10),
])
def test_invalid_addresses_rejected(chain, addr):
    with pytest.raises(InvalidAddress):
        normalize_address(BY_SLUG[chain], addr)


def test_quote_assets():
    assert is_quote_asset(BY_SLUG["base"], "0x4200000000000000000000000000000000000006")
    assert not is_quote_asset(BY_SLUG["base"], "0x1111111111111111111111111111111111111111")
