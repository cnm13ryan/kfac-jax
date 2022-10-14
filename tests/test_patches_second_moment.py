# Copyright 2022 DeepMind Technologies Limited. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Testing the functionality of the patches second moment computation."""
import itertools
from typing import Tuple, Union

from absl.testing import absltest
from absl.testing import parameterized
import jax
from jax import lax
import jax.numpy as jnp
import kfac_jax
import numpy as np

psm = kfac_jax.patches_second_moment
utils = kfac_jax.utils


class TestPatchesMoments(parameterized.TestCase):
  """Test class for the patches second moment functions."""

  def assertAllClose(
      self,
      x: utils.PyTree,
      y: utils.PyTree,
      check_dtypes: bool = True,
      atol: float = 1e-6,
      rtol: float = 1e-6,
  ):
    """Asserts that the two PyTrees are close up to the provided tolerances."""
    x_v, x_tree = jax.tree_util.tree_flatten(x)
    y_v, y_tree = jax.tree_util.tree_flatten(y)
    self.assertEqual(x_tree, y_tree)
    for xi, yi in zip(x_v, y_v):
      self.assertEqual(xi.shape, yi.shape)
      if check_dtypes:
        self.assertEqual(xi.dtype, yi.dtype)
      np.testing.assert_allclose(xi, yi, rtol=rtol, atol=atol)

  @parameterized.parameters(list(itertools.product(
      [8, 16],  # h
      [(1, 2), (3, 3), (4, 5)],  # kernel_shape
      [(1, 1), (1, 2), (1, 3),
       (2, 2), (2, 3), (3, 3)],  # strides
      ["VALID", "SAME"],  # padding
  )) + [
      (9, (2, 2), (2, 2), ((0, 0), (2, 3))),  # custom padding
      (8, (2, 2), (1, 3), ((0, 1), (2, 3))),  # custom padding
  ])
  def test_num_locations(
      self,
      h_and_w: int,
      kernel_shape: Tuple[int, int],
      strides: Tuple[int, int],
      padding: Union[str, Tuple[Tuple[int, int], Tuple[int, int]]],
  ):
    """Tests calculation of the number of convolutional locations."""
    spatial_shape = (h_and_w, h_and_w)
    patches = lax.conv_general_dilated_patches(
        jnp.zeros((1,) + spatial_shape + (3,)),
        filter_shape=kernel_shape,
        window_strides=strides,
        padding=padding,
        dimension_numbers=("NHWC", "IOHW", "NHWC"),
    )
    num_locations = patches.size // patches.shape[-1]
    num_location_fast = psm.num_conv_locations(
        spatial_shape,
        kernel_spatial_shape=kernel_shape,
        spatial_strides=strides,
        spatial_padding=padding)
    self.assertEqual(num_locations, num_location_fast)

  @parameterized.parameters(list(itertools.product(
      [3],  # c
      [8, 16],  # h
      [(1, 2), (3, 3), (4, 5)],  # kernel_shape
      [(1, 1), (1, 2), (1, 3),
       (2, 2), (2, 3), (3, 3)],  # strides
      ["VALID", "SAME"],  # padding
      ["NHWC", "NCHW"],  # data_format
      [False, True],  # per_channel
  )) + [
      (3, 9, (2, 2), (2, 2), ((0, 0), (2, 3)), "NHWC", False),  # custom padding
      (3, 9, (2, 2), (2, 2), ((0, 0), (2, 3)), "NHWC", True),  # custom padding
      (3, 8, (2, 2), (1, 3), ((0, 1), (2, 3)), "NHWC", False),  # custom padding
      (3, 8, (2, 2), (1, 3), ((0, 1), (2, 3)), "NHWC", True),  # custom padding
  ])
  def test_patches_moments_2d(
      self,
      c: int,
      h_and_w: int,
      kernel_shape: Tuple[int, int],
      strides: Tuple[int, int],
      padding: Union[str, Tuple[Tuple[int, int], Tuple[int, int]]],
      data_format: str,
      per_channel: bool,
  ):
    """Tests the patches second moment calculation for 2D convolution."""
    rng = jax.random.PRNGKey(1214321)
    n = 5
    if data_format == "NHWC":
      shape = (n, h_and_w, h_and_w, c)
    else:
      shape = (n, c, h_and_w, h_and_w)
    num_locations = psm.num_conv_locations(
        (h_and_w, h_and_w),
        kernel_spatial_shape=kernel_shape,
        spatial_strides=strides,
        spatial_padding=padding)
    feature_group_count = c if per_channel else 1

    ones_inputs = jnp.ones(shape)
    key, rng = jax.random.split(rng)
    random_inputs = jax.random.normal(key, shape)
    random_inputs = jnp.asarray(random_inputs.astype(ones_inputs.dtype))
    for inputs in (ones_inputs, random_inputs):
      matrix, vector = psm.patches_moments_explicit(
          inputs,
          kernel_spatial_shape=kernel_shape,
          strides=strides,
          padding=padding,
          data_format=data_format,
          feature_group_count=feature_group_count,
          unroll_loop=True,
          precision=jax.lax.Precision.HIGHEST,
      )
      matrix_fast, vector_fast = psm.patches_moments(
          inputs,
          kernel_spatial_shape=kernel_shape,
          strides=strides,
          padding=padding,
          data_format=data_format,
          feature_group_count=feature_group_count,
          precision=jax.lax.Precision.HIGHEST,
      )

      # For accurate results we compare the mean over the batch and locations
      normalizer = n * num_locations
      matrix, vector, matrix_fast, vector_fast = jax.tree_util.tree_map(
          lambda x: x / normalizer, (matrix, vector, matrix_fast, vector_fast)  # pylint: disable=cell-var-from-loop
      )
      self.assertAllClose(matrix, matrix_fast)
      self.assertAllClose(vector, vector_fast)


if __name__ == "__main__":
  absltest.main()
