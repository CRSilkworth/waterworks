import transform as n
import pandas as pd
import numpy as np
import datetime
import warnings
import reversible_transforms.waterworks.placeholder as pl
import reversible_transforms.tanks.tank_defs as td
import reversible_transforms.waterworks.waterwork as wa

class DateTimeTransform(n.Transform):
  """Class used to create mappings from raw datetime data to vectorized, normalized data and vice versa.

  Parameters
  ----------
  df : pd.DataFrame
    The dataframe with all the data used to define the mappings.
  columns : list of strs
    The column names of all the relevant columns that make up the data to be taken from the dataframe
  start_datetimes: list of datetimes
    The 'zero times' for each of the columns. Must be the same length as columns
  from_file : str
    The path to the saved file to recreate the transform object that was saved to disk.
  save_dict : dict
    The dictionary to rereate the transform object

  Attributes
  ----------
  attribute_list : list of strs
    The list of attributes that need to be saved in order to fully reconstruct the transform object.

  """
  attribute_dict = {'norm_mode': None, 'norm_axis': None, 'num_units': 1, 'time_unit': 'D', 'fill_nat_func': None, 'name': '', 'mean': None, 'std': None, 'min': None, 'max': None, 'dtype': np.float64, 'input_dtype': None, 'zero_datetime': datetime.datetime(1970, 1, 1)}

  def _setattributes(self, **kwargs):
    super(DateTimeTransform, self)._setattributes(self.attribute_dict, **kwargs)

    if self.norm_mode not in (None, 'min_max', 'mean_std'):
      raise ValueError(self.norm_mode + " not a valid norm mode.")

    if type(self.zero_datetime) is datetime.datetime:
      self.zero_datetime = np.datetime64(self.zero_datetime)

    if self.fill_nat_func is None:
      self.fill_nat_func = lambda array: np.full(array[np.isnat(array)].shape, self.zero_datetime)

  def calc_global_values(self, array, verbose=True):
    """Set all the relevant attributes for this subclass. Called by the constructor for the Transform class.

    Parameters
    ----------
    df : pd.DataFrame
      The dataframe with all the data used to define the mappings.
    columns : list of strs
      The column names of all the relevant columns that make up the data to be taken from the dataframe
    start_datetimes: list of datetimes
      The 'zero times' for each of the columns. Must be the same length as columns

    """
    # Get the inputted dtype
    self.input_dtype = array.dtype

    if self.norm_mode == 'mean_std':
      # Find the means and standard deviations of each column
      temp_array = (array - self.zero_datetime)/np.timedelta64(self.num_units, self.time_unit)
      temp_array = temp_array.astype(self.dtype)

      if not len(temp_array):
        raise ValueError("Inputted col_array has no non nan values.")

      self.mean = np.nanmean(temp_array, axis=self.norm_axis)
      self.std = np.nanstd(temp_array, axis=self.norm_axis)

      # If any of the standard deviations are 0, replace them with 1's and
      # print out a warning
      if (self.std == 0).any():
        if verbose:
          warnings.warn("DatetimeTransform " + self.name + " has a zero-valued std, replacing with 1.")
        self.std[self.std == 0] = 1.0

    elif self.norm_mode == 'min_max':
      # Find the means and standard deviations of each column
      # temp_col_array = col_array[~np.isnat(col_array)]
      temp_array = (array - self.zero_datetime)/np.timedelta64(self.num_units, self.time_unit)
      temp_array = temp_array.astype(self.dtype)

      if not len(temp_array):
        raise ValueError("Inputted col_array has no non nan values.")

      self.min = np.nanmin(temp_array, axis=self.norm_axis)
      self.max = np.nanmax(temp_array, axis=self.norm_axis)

      # Test to make sure that min and max are not equal. If they are replace
      # with default values.
      if self.min == self.max:
        self.max = self.max + 1

        if verbose:
          warnings.warn("DatetimeTransform " + self.name + " the same values for min and max, replacing with " + str(self.min) + " " + str(self.max) + " respectively.")

  def get_waterwork(self):
    assert self.input_dtype is not None, ("Run calc_global_values before running the transform")

    with wa.Waterwork(name=self.name) as ww:
      input = pl.Placeholder(np.ndarray, self.input_dtype, name='input')

      # Replace all the NaT's with the inputted replace_with.
      nats = td.isnat(input)

      replace_with = pl.Placeholder(np.ndarray, self.input_dtype, name='replace_with')
      replaced = td.replace(nats['a'], nats['target'], replace_with, name='rp')

      replaced['replaced_vals'].set_name('replaced_vals')
      replaced['mask'].set_name('nats')

      nums = td.datetime_to_num(replaced['target'], self.zero_datetime, self.num_units, self.time_unit, name='dtn')
      nums['diff'].set_name('diff')

      if self.norm_mode == 'mean_std':
        nums = nums['target'] - self.mean
        nums = nums['target'] / self.std
      elif self.norm_mode == 'min_max':
        nums = nums['target'] - self.min
        nums = nums['target'] / (self.max - self.min)

      nums['target'].set_name('nums')

    return ww

  def pour(self, array):
    ww = self.get_waterwork()

    tap_dict = ww.pour(
      {'input': array, 'replace_with': self.fill_nat_func(array)},
      key_type='str'
    )

    return {k: tap_dict[k] for k in ['nums', 'nats', 'diff']}

  def pump(self, nums, nats, diff):
    ww = self.get_waterwork()

    num_nats = len(np.where(nats)[0])
    tap_dict = {
      'nums': nums,
      'nats': nats,
      'replaced_vals': np.full([num_nats], 'NaT', dtype=self.input_dtype),
      'diff': diff,
      (self._name('dtn'), 'zero_datetime'): self.zero_datetime,
      (self._name('dtn'), 'time_unit'): self.time_unit,
      (self._name('dtn'), 'num_units'): self.num_units,
      (self._name('rp'), 'replace_with_shape'): (num_nats,),
    }
    if self.norm_mode == 'mean_std' or self.norm_mode == 'min_max':
      if self.norm_mode == 'mean_std':
        sub_val = self.mean
        div_val = self.std
      else:
        sub_val = self.min
        div_val = self.max - self.min
      norm_mode_dict = {
        ('SubTyped_0', 'smaller_size_array'): sub_val,
        ('SubTyped_0', 'a_is_smaller'): False,
        ('DivTyped_0', 'smaller_size_array'): div_val,
        ('DivTyped_0', 'a_is_smaller'): False,
        ('DivTyped_0', 'remainder'): np.array([], dtype=self.input_dtype),
        ('DivTyped_0', 'missing_vals'): np.array([], dtype=float)
      }
      tap_dict.update(norm_mode_dict)
    ww.pump(tap_dict, key_type='str')
    array = ww.get_placeholder('input').get_val()

    return array
  # def forward_transform(self, array, verbose=True):
  #   """Convert a row in a dataframe to a vector.
  #
  #   Parameters
  #   ----------
  #   row : pd.Series
  #     A row in a dataframe where the index is the column name and the value is the column value.
  #   verbose : bool
  #     Whether or not to print out warnings.
  #
  #   Returns
  #   -------
  #   np.array(
  #     shape=[len(self)],
  #     dtype=np.float64
  #   )
  #     The vectorized and normalized data.
  #
  #   """
  #   assert self.input_dtype is not None, ("Run calc_global_values before running the transform")
  #
  #   col = array[:, self.col_index: self.col_index + 1]
  #   isnan = np.isnat(col)
  #
  #   if self.fill_nan_func is not None:
  #     col = self.fill_nan_func(array, self.col_index)
  #
  #   # Find the total seconds since the start time
  #   secs = (col - self.zero_datetime)/np.timedelta64(1, 's')
  #   secs = secs.astype(self.dtype)
  #
  #   # Subtract out the mean and divide by the standard deviation to give a
  #   # mean of zero and standard deviation of one.
  #   if self.norm_mode == 'mean_std':
  #     secs = (secs - self.mean) / self.std
  #   elif self.norm_mode == 'min_max':
  #     secs = (secs - self.min) / (self.max - self.min)
  #
  #   # Convert them to a vector
  #   return {'isnan': isnan, 'data': secs}
  #
  # def seconds_to_vector(self, seconds, verbose=True):
  #   """Convert the total seconds since start time to vectorized and normalized data.
  #
  #   Parameters
  #   ----------
  #   seconds : list of numerical
  #     The seconds to be normalized and converted into the a vector.
  #   verbose : bool
  #     Whether or not to print out warnings.
  #
  #   Returns
  #   -------
  #   np.array(
  #     shape=[len(self)],
  #     dtype=np.float64
  #   )
  #     The vectorized and normalized data.
  #
  #   """
  #   # Create an array from the inputted seconds, subtract out the mean and
  #   # divide by the standard deviation giving a mean of zero and and
  #   # standard deviation of one.
  #   vector = np.array(seconds, dtype=np.float64)
  #   if self.mean_std:
  #     vector = (vector - self.means) / self.stds
  #
  #   return vector
  #
  # def backward_transform(self, arrays_dict, verbose=True):
  #   """Convert the vectorized and normalized data back into it's raw dataframe row.
  #
  #   Parameters
  #   ----------
  #   vector : np.array(
  #     shape=[len(self)],
  #     dtype=np.float64
  #   )
  #     The vectorized and normalized data.
  #   verbose : bool
  #     Whether or not to print out warnings.
  #
  #   Returns
  #   -------
  #   row : pd.Series
  #     A row in a dataframe where the index is the column name and the value is the column value.
  #
  #   """
  #   assert self.input_dtype is not None, ("Run calc_global_values before running the transform")
  #   col = np.array(arrays_dict['data'], copy=True)
  #   col[arrays_dict['isnan']] = np.datetime64('NaT')
  #
  #   # Undo the mean/std or min/max normalizations to give back the unscaled
  #   # values.
  #   if self.norm_mode == 'mean_std':
  #     col = col * self.std + self.mean
  #   elif self.norm_mode == 'min_max':
  #     col = col * (self.max - self.min) + self.min
  #
  #   col = self.zero_datetime + col * np.timedelta64(1, 's')
  #
  #   return col.astype(self.input_dtype)
