const taxRate = 0.18;

function calcTotal(cartItems) {
  let totalPrice = 0;
  for (const item of cartItems) {
    totalPrice += item.price * item.qty;
  }
  return totalPrice * (1 + taxRate);
}
